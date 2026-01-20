import logging
from typing import Annotated, Optional
from livekit.agents import llm
from db import db
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger("reservation-agent")

def format_datetime_human(iso_string: str) -> str:
    """Convert ISO datetime to human-friendly format."""
    try:
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        return dt.strftime("%A, %B %d at %I:%M %p")
    except:
        return iso_string


class ReservationTools:
    def __init__(self, room, end_event: asyncio.Event = None):
        self._user_id = None
        self._user_context = None
        self._room = room
        self._end_event = end_event
        self._session_bookings = []  # Track bookings made in this session
        self._session_preferences = []  # Track mentioned preferences
    
    def get_session_data(self) -> dict:
        """Export session data for summary generation."""
        return {
            "user": self._user_context,
            "bookings": self._session_bookings,
            "preferences": self._session_preferences
        }

    async def _publish_update(self, tool_name: str, data: dict):
        if self._room:
            import json
            payload = json.dumps({"type": "tool_call", "tool": tool_name, "data": data})
            logger.info(f"Publishing tool update: {payload}")
            # Ensure we publish to the room from the agent's identity
            await self._room.local_participant.publish_data(payload, reliable=True)

    @llm.function_tool
    async def identify_user(
        self, 
        contact_number: Annotated[str, "The user's contact number, which can be provided in any spoken format (e.g., 'five five five, one two three, four five six seven' or 'five five five one two three four five six seven'). The tool will automatically extract the digits."],
        name: Annotated[Optional[str], "The user's full name"] = None
    ):
        """Identify the user by their phone number and name."""
        # Normalize phone number: extract digits and keep last 10 for consistency
        digits = ''.join(filter(str.isdigit, contact_number))
        if len(digits) < 10:
             return f"Error: '{contact_number}' is not a valid phone number. Please provide at least 10 digits."
        
        normalized_number = digits[-10:] # standardized 10-digit format
        
        logger.info(f"Identifying user with contact: {normalized_number}, Name: {name}")
        await self._publish_update("identify_user", {"contact_number": normalized_number, "name": name, "status": "started"})
        
        user = await db.get_or_create_user(normalized_number, name)
        self._user_id = user["id"]
        self._user_context = user
        
        await self._publish_update("identify_user", {"status": "completed", "user": user})
        return f"User identified: {user.get('name', 'Unknown Name')}."

    @llm.function_tool
    async def fetch_slots(self):
        """Fetch available appointment slots for today and tomorrow."""
        logger.info("Fetching slots")
        await self._publish_update("fetch_slots", {"status": "started"})
        
        now = datetime.now()
        slots = []
        
        # Available hours
        available_hours = [10, 14, 17, 18, 19, 20, 21]
        
        # Check Today and Tomorrow
        for day_offset in range(2):
            date = now + timedelta(days=day_offset)
            date_str = date.strftime("%Y-%m-%d")
            day_label = "Today" if day_offset == 0 else "Tomorrow"
            
            for hour in available_hours:
                slot_time = datetime.combine(date.date(), datetime.min.time().replace(hour=hour))
                if slot_time > now:
                    slots.append({
                        "iso": slot_time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "display": f"{day_label} at {slot_time.strftime('%I:%M %p')}"
                    })
        
        await self._publish_update("fetch_slots", {"status": "completed", "slots": slots[:8]})
        slot_list = ', '.join([s['display'] for s in slots[:8]])
        return f"Marriot Kochi availability for next 24 hours: {slot_list}. When booking, use the ISO format."

    @llm.function_tool
    async def book_appointment(
        self,
        start_time: Annotated[str, "The start time of the appointment (ISO format e.g. '2023-10-27T19:00:00')"],
        num_people: Annotated[int, "The number of people for the reservation"],
        name: Annotated[Optional[str], "The user's full name (if not already identified)"] = None,
        contact_number: Annotated[Optional[str], "The user's contact number (if not already identified)"] = None,
        details: Annotated[str, "Additional details for the appointment"] = "General Reservation"
    ):
        """Book an appointment. If user is not identified yet, provide name and contact_number to identify and book in one step."""
        await self._publish_update("book_appointment", {"status": "started", "start_time": start_time, "num_people": num_people})
        
        # Implicit Identification Logic
        if not self._user_id:
            if contact_number:
                # Normalize phone number: extract digits and keep last 10
                digits = ''.join(filter(str.isdigit, contact_number))
                if len(digits) < 10:
                    await self._publish_update("book_appointment", {"status": "failed", "reason": "invalid_phone"})
                    return f"Error: '{contact_number}' is not a valid 10-digit phone number."
                
                normalized_number = digits[-10:]
                
                logger.info(f"Implicitly identifying user: {normalized_number}, Name: {name}")
                user = await db.get_or_create_user(normalized_number, name)
                self._user_id = user["id"]
                self._user_context = user
                await self._publish_update("identify_user", {"status": "completed", "user": user, "implicit": True})
            else:
                 await self._publish_update("book_appointment", {"status": "failed", "reason": "auth_required"})
                 return "Error: I need your name and phone number to book the appointment. Please provide them."
        
        logger.info(f"Booking appointment for {self._user_id} at {start_time} for {num_people} people")
        
        is_available = await db.check_availability(start_time, num_people)
        if not is_available:
            # Check if it was a past date
            try:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                is_past = dt.timestamp() < datetime.now().timestamp()
            except:
                is_past = False

            # Find next available slot to suggest
            next_slot = await db.get_next_available_slot(start_time)
            await self._publish_update("book_appointment", {"status": "failed", "reason": "past_date" if is_past else "unavailable", "next_slot": next_slot})
            
            if is_past:
                next_human = format_datetime_human(next_slot) if next_slot else "another time"
                return f"I'm sorry, Marriot Kochi only accepts reservations for future dates. The earliest available slot I can offer you is {next_human}. Would you like me to book that for you?"

            if next_slot:
                next_human = format_datetime_human(next_slot)
                return f"I'm sorry, that time slot is already booked. The next available slot is {next_human}. Would you like me to book that instead?"
            else:
                return "I'm sorry, that time slot is not available and I couldn't find another available slot in the next week. Please try a different date."

        appt = await db.create_appointment(self._user_id, start_time, num_people, details)
        self._session_bookings.append(appt)  # Track for summary
        await self._publish_update("book_appointment", {"status": "completed", "appointment": appt})
        
        user_name = self._user_context.get('name', 'Guest') if self._user_context else 'Guest'
        human_time = format_datetime_human(start_time)
        return f"Wonderful! I've booked your table, {user_name}. Your reservation is confirmed for {human_time} for {num_people} guests (ID: {appt['id']}). We look forward to seeing you!"

    @llm.function_tool
    async def retrieve_appointments(self):
        """Retrieve past appointments for the current user."""
        await self._publish_update("retrieve_appointments", {"status": "started"})
        
        if not self._user_id:
             return "Error: Please identify the user first using 'identify_user'."
        
        logger.info(f"Retrieving appointments for {self._user_id}")
        appts = await db.get_user_appointments(self._user_id)
        if not appts:
            await self._publish_update("retrieve_appointments", {"status": "completed", "count": 0})
            return "No existing appointments found."
        
        appt_summaries = []
        for a in appts:
            human_time = format_datetime_human(a['start_time'])
            # Include ID for the agent to use, even if it doesn't say it aloud
            appt_summaries.append(f"- {human_time} (Status: {a['status']}, ID: {a['id']})")
        
        await self._publish_update("retrieve_appointments", {"status": "completed", "appointments": appts})
        return "I found the following appointments for you. Which one would you like to manage?\n" + "\n".join(appt_summaries)

    @llm.function_tool
    async def cancel_appointment(
        self,
        appointment_id: Annotated[str, "The ID of the appointment to cancel"]
    ):
        """Cancel an appointment."""
        logger.info(f"Cancelling appointment {appointment_id}")
        await self._publish_update("cancel_appointment", {"status": "started", "appointment_id": appointment_id})
        
        success = await db.cancel_appointment(appointment_id)
        if success:
            await self._publish_update("cancel_appointment", {"status": "completed"})
            return f"Appointment {appointment_id} has been cancelled."
        else:
            await self._publish_update("cancel_appointment", {"status": "failed", "reason": "not_found"})
            return f"Error: Could not find appointment {appointment_id} or it's already cancelled."

    @llm.function_tool
    async def modify_appointment(
        self,
        appointment_id: Annotated[str, "The ID of the appointment to modify"],
        new_start_time: Annotated[Optional[str], "The new desired start time (ISO format)"] = None,
        new_num_people: Annotated[Optional[int], "The new party size"] = None,
        new_details: Annotated[Optional[str], "Updated details or preferences"] = None
    ):
        """Modify an existing appointment. User MUST be identified first. Shows current booking details before making changes."""
        if not new_start_time and not new_num_people and not new_details:
            return "Error: Please specify what you want to change (time, party size, or details)."
        
        logger.info(f"Modifying appointment {appointment_id}")
        await self._publish_update("modify_appointment", {"status": "started", "appointment_id": appointment_id})
        
        if not self._user_id:
            return "I need to verify your identity first. Please provide your phone number so I can look up your reservations."
        
        # Get the original appointment details
        appts = await db.get_user_appointments(self._user_id)
        original = next((a for a in appts if a['id'] == appointment_id), None)
        if not original:
            await self._publish_update("modify_appointment", {"status": "failed", "reason": "not_found"})
            return f"Error: Could not find that appointment in your reservations. Would you like me to show you your current bookings?"
        
        # Show current details
        current_time = format_datetime_human(original['start_time'])
        current_people = original.get('num_people', 2)
        
        final_time = new_start_time or original['start_time']
        final_people = new_num_people or current_people
        final_details = new_details or original.get('details', 'General Reservation')
        
        # Check availability for the new time
        if new_start_time:
            is_available = await db.check_availability(final_time, final_people)
            if not is_available:
                # Check if it was a past date
                try:
                    dt = datetime.fromisoformat(final_time.replace('Z', '+00:00'))
                    is_past = dt.timestamp() < datetime.now().timestamp()
                except:
                    is_past = False

                next_slot = await db.get_next_available_slot(final_time)
                await self._publish_update("modify_appointment", {"status": "failed", "reason": "past_date" if is_past else "new_slot_unavailable"})
                
                if is_past:
                    next_human = format_datetime_human(next_slot) if next_slot else "another time"
                    return f"I'm sorry, we can only modify reservations to a future date. The earliest available slot is {next_human}. Your current reservation remains at {current_time}."

                if next_slot:
                    next_human = format_datetime_human(next_slot)
                    return f"I'm sorry, {format_datetime_human(final_time)} is already booked. Your current reservation is for {current_time} for {current_people} guests. The next available slot is {next_human}. Would you like that instead?"
                return f"I'm sorry, that slot is not available. Your current reservation remains at {current_time} for {current_people} guests."
        
        # Cancel old and create new
        await db.cancel_appointment(appointment_id)
        appt = await db.create_appointment(self._user_id, final_time, final_people, final_details)
        
        await self._publish_update("modify_appointment", {"status": "completed", "new_appointment": appt})
        new_human_time = format_datetime_human(final_time)
        
        user_name = self._user_context.get('name', 'Guest') if self._user_context else 'Guest'
        return f"Certainly, {user_name}. I've updated your reservation. It is now set for {new_human_time} for {final_people} guests (ID: {appt['id']}). Is there anything else I can assist you with?"

    @llm.function_tool
    async def update_booking_details(
        self,
        appointment_id: Annotated[str, "The ID of the appointment to update"],
        details: Annotated[str, "The special occasion or dietary requirements to add"]
    ):
        """Update specific details like special occasions or dietary requirements for a booking."""
        logger.info(f"Updating details for appointment {appointment_id}")
        await self._publish_update("update_booking_details", {"status": "started", "appointment_id": appointment_id})
        
        success = await db.update_appointment(appointment_id, details)
        if success:
            await self._publish_update("update_booking_details", {"status": "completed"})
            return f"Thank you for sharing those details. I've added the following to your reservation: '{details}'. Our team will ensure everything is prepared for you."
        else:
            await self._publish_update("update_booking_details", {"status": "failed", "reason": "not_found"})
            return f"I apologize, but I couldn't find that reservation to update. Would you like me to check your active bookings?"

    @llm.function_tool
    async def end_conversation(self):
        """CALL THIS TOOL when the user is done, says goodbye, or wants to end the call. 
        It triggers the final summary and closes the session gracefully.
        """
        logger.info("Ending conversation tool called")
        if self._end_event:
            self._end_event.set()
        return "The conversation is now ending. Goodbye!"
