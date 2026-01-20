import asyncio
from datetime import datetime
import logging
import os
import json
from dotenv import load_dotenv

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, cartesia, openai, silero, bey

from tools import ReservationTools

load_dotenv()
logger = logging.getLogger("reservation-agent")
logger.info("Worker script started")

async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for user to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    # Initialize plugins
    logger.info("Initializing STT, TTS, and LLM plugins...")
    stt_plugin = deepgram.STT()
    
    try:
        tts_plugin = deepgram.TTS() 
    except Exception as e:
        logger.warning(f"Failed to init Deepgram TTS, falling back to OpenAI: {e}")
        tts_plugin = openai.TTS()

    try:
        llm_plugin = openai.LLM(model="gpt-4o-mini")
    except Exception as e:
        logger.warning(f"Failed to init OpenAI LLM, falling back to Gemini: {e}")
        llm_plugin = google.LLM(model="gemini-2.0-flash-001")
    
    logger.info("Plugins initialized successfully.")

    try:
        # Tuned VAD settings for faster turn-taking
        vad = silero.VAD.load(min_speech_duration=0.1, min_silence_duration=0.5)
    except Exception as e:
        logger.warning(f"Could not load Silero VAD: {e}")
        vad = None

    current_time_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    instructions = (
        "You are the sophisticated Guest Service AI for the Marriott Kochi Reservation Helpline. "
        f"The current date and time is {current_time_str}. "
        "Your persona is refined, warm, professional, and empathetic—embodying the Marriott 'Spirit to Serve.' "
        "Your goal is to provide a seamless, premium reservation experience. "
        "\n1. GREETING: Always greet as 'Marriott Kochi Reservation Helpline. It is a pleasure to assist you today.' "
        "\n2. PERSONALIZATION: Always ask for the guest's Name and Phone Number early. Use `identify_user`. "
        "Address the guest by name once identified to create a personalized experience. "
        "\n3. RESERVATIONS: When booking, ask for the Date, Time, and Party Size. "
        "   - Restaurant Hours: 10:00 AM to 10:00 PM. "
        "   - POLICY: We only accept future reservations. If a past date is requested, politely explain: 'I apologize, but we can only secure reservations for future dates. May I suggest an alternative?' "
        "   - Use `book_appointment` for the booking. "
        "\n4. GUEST PREFERENCES: After a successful booking, always ask: 'Is there a special occasion you are celebrating, or any dietary requirements our chefs should be aware of?' "
        "\n5. MODIFICATIONS: For modify/cancel requests, prioritize finding the record first via phone number and `retrieve_appointments`. "
        "Confirm the specific details (Time/Guests) before making changes. Use the IDs returned by the tool. "
        "\n6. VOICE STYLE: Keep responses elegant and concise. Avoid robotic lists; use natural transitions like 'Certainly,' 'I would be delighted to,' and 'Thank you for your patience.' "
        "\n7. CLOSING: Once the guest is satisfied, use the `end_conversation` tool and wish them an extraordinary day: 'We look forward to welcoming you to Marriott Kochi. Have a wonderful day.' "
    )
    
    # Signal for graceful shutdown
    end_event = asyncio.Event()

    # Initialize tools with room context and shutdown signal
    tools_inst = ReservationTools(room=ctx.room, end_event=end_event)
    tools = llm.find_function_tools(tools_inst)

    # Create the Agent (holds state and logic)
    agent = Agent(
        instructions=instructions,
        tools=tools,
    )

    @ctx.room.on("participant_connected")
    def _on_participant_connected(participant):
        logger.info(f"Participant connected: {participant.identity}")

    @ctx.room.on("track_subscribed")
    def _on_track_subscribed(track, publication, participant):
        logger.info(f"Track subscribed: {track.kind} from {participant.identity}")

    @ctx.room.on("track_published")
    def _on_track_published(publication, participant):
        logger.info(f"Track published: {publication.kind} by {participant.identity}")

    # Create the AgentSession (the orchestrator)
    session = AgentSession(
        vad=vad,
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
    )

    # Initialize Beyond Presence Avatar (optional, controlled by ENABLE_AVATAR flag)
    enable_avatar = os.getenv("ENABLE_AVATAR", "false").lower() == "true"
    bey_api_key = os.getenv("BEY_API_KEY")
    bey_avatar_id = os.getenv("BEY_AVATAR_ID")
    
    if enable_avatar and bey_api_key and bey_avatar_id:
        logger.info(f"Initializing Beyond Presence Avatar: {bey_avatar_id}")
        avatar_session = bey.AvatarSession(
            avatar_id=bey_avatar_id,
            api_key=bey_api_key,
        )
        # Start the avatar session synced with the agent session
        await avatar_session.start(session, room=ctx.room)
        logger.info("Avatar session started.")
    else:
        if not enable_avatar:
            logger.info("Avatar disabled (ENABLE_AVATAR=false). Running voice-only mode.")
        else:
            logger.warning("BEY_API_KEY or BEY_AVATAR_ID not found. Avatar will not be active.")

    # Start the session
    await session.start(agent, room=ctx.room)
    
    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev):
        if ev.transcript:
            logger.info(f"STT: {ev.transcript} (final={ev.is_final})")

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev):
        logger.info(f"Agent state changed: {ev.old_state} -> {ev.new_state}")

    @session.on("user_state_changed")
    def _on_user_state_changed(ev):
        logger.info(f"User state changed: {ev.old_state} -> {ev.new_state}")

    @session.on("llm_text_chunk_received")
    def _on_llm_chunk(ev):
        # logger.debug(f"LLM Chunk: {ev.text_chunk}")
        pass

    @session.on("error")
    def _on_session_error(ev):
        logger.error(f"Session error: {ev.error}")

    # Greet the user
    logger.info("Greeting the user...")
    await session.say("Hello! This is Marriot Kochi Reservation Helpline. How can I assist you?", allow_interruptions=True)
    logger.info("Greeting finished.")

    async def send_summary():
        # Generate Summary
        logger.info("Generating conversation summary...")
        chat_items = session.history.items
        
        transcript_lines = []
        for item in chat_items:
            if isinstance(item, llm.ChatMessage):
                content = item.text_content or ""
                if content:
                    transcript_lines.append(f"{item.role}: {content}")
        
        transcript = "\n".join(transcript_lines)
        
        if not transcript:
            logger.info("No transcript to summarize.")
            return

        # Get session data from tools
        session_data = tools_inst.get_session_data()
        user_info = session_data.get("user") or {}
        bookings = session_data.get("bookings") or []
        
        # Build structured booking info
        booking_info = ""
        if bookings:
            booking_lines = []
            for b in bookings:
                booking_lines.append(f"- Time: {b.get('start_time')}, Party size: {b.get('num_people', 'N/A')}, Status: {b.get('status', 'booked')}")
            booking_info = "\\n".join(booking_lines)
        else:
            booking_info = "No bookings made during this call."
        
        # Current timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        summary_prompt = (
            f"Generate a concise, professional summary of this Marriot Kochi Reservation call.\\n\\n"
            f"**Call Timestamp:** {timestamp}\\n"
            f"**Customer Name:** {user_info.get('name', 'Unknown')}\\n"
            f"**Contact Number:** {user_info.get('contact_number', 'Unknown')}\\n\\n"
            f"**Bookings Made:**\\n{booking_info}\\n\\n"
            f"**Conversation Transcript:**\\n{transcript}\\n\\n"
            f"Include:\\n"
            f"1. Brief summary of the discussion\\n"
            f"2. All bookings with date/time and party size\\n"
            f"3. Any special requests or preferences mentioned\\n"
            f"4. Next steps if any\\n"
            f"Format as clean markdown."
        )
        
        try:
            summary_ctx = llm.ChatContext()
            summary_ctx.add_message(role="user", content=summary_prompt)
            
            stream = llm_plugin.chat(chat_ctx=summary_ctx)
            
            full_summary = ""
            async for text in stream.to_str_iterable():
                full_summary += text
            
            logger.info(f"Summary generated: {full_summary}")
            
            # Save summary to database
            from db import db
            user_id = user_info.get("id") if user_info else None
            await db.save_summary(user_id, full_summary, bookings, timestamp)
            logger.info("Summary saved to database.")
            
            if ctx.room.isconnected():
                 payload = json.dumps({"type": "summary", "content": full_summary, "timestamp": timestamp})
                 await ctx.room.local_participant.publish_data(payload, reliable=True)
                 logger.info("Summary published to room.")
            
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")

    # Wait for the participant to disconnect or tool to end
    while ctx.room.isconnected():
        if end_event.is_set():
            logger.info("Conversation end signal detected! Sending summary proactively...")
            await send_summary()
            break
        await asyncio.sleep(0.5)

    # If it was a natural disconnect (loop ended without break), still try final summary
    if not end_event.is_set():
        await send_summary()
    
    # Briefly wait to ensure all data is transmitted
    await asyncio.sleep(2)
    logger.info("Session entrypoint finishing.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
