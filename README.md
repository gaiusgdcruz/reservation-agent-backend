#Reservation Agent - Backend

This is the LiveKit-powered voice agent backend for the Marriott Kochi Reservation Helpline, designed to provide a sophisticated and empathetic reservation experience.

## Architecture & Overview
- **Voice Framework**: LiveKit Agents (Python)
- **STT**: Deepgram
- **TTS**: Cartesia
- **LLM**: Gemini (Google) - *Note: `main.py` currently defaults to OpenAI GPT-4o-mini for LLM, and OpenAI TTS if Cartesia fails.*
- **Avatar**: LiveKit Video / Beyond Presence Integration (Stub)
- **Database**: Supabase

## 🚀 Deployment Instructions (Railway)

1.  **Create GitHub Repo**: Create a new repository on GitHub named `reservation-agent-backend`.
2.  **Push Code**:
    ```bash
    git remote add origin https://github.com/YOUR_USERNAME/reservation-agent-backend.git
    git branch -M main
    git push -u origin main
    ```
3.  **Deploy on Railway**:
    - Log in to [Railway.app](https://railway.app).
    - Create a new project -> **Deploy from GitHub repo**.
    - Select this repository.
    - **Environment Variables**: Add all variables from your local `.env` file to the Railway dashboard:
        - `LIVEKIT_URL`
        - `LIVEKIT_API_KEY`
        - `LIVEKIT_API_SECRET`
        - `DEEPGRAM_API_KEY`
        - `GOOGLE_API_KEY` (if using Gemini)
        - `OPENAI_API_KEY` (if using GPT)
        - `SUPABASE_URL`
        - `SUPABASE_KEY`
    - Railway will automatically detect the `Procfile` and start the worker.

## Local Development

1.  Install dependencies: `pip install -r requirements.txt`
2.  Run dev worker: `python main.py dev`

## Features
- **Real-time Voice Conversation**: Low latency interaction.
- **Visual Avatar**: Syncs with the agent.
- **Tool Calling**: The agent leverages several tools to manage reservations and user interactions.
- **Conversation Summary**: Auto-generated at the end of the call.

## Agent Tools

The agent interacts with the database and manages conversations using the following tools:

### `identify_user(contact_number: str, name: Optional[str])`
- **Description**: Identify the user by their phone number and name.
- **Parameters**:
    - `contact_number` (str): The user's contact number, which can be provided in any spoken format. The tool will automatically extract the digits.
    - `name` (Optional[str]): The user's full name.
- **Notes**: The tool normalizes the phone number to a 10-digit format by extracting only digits.

### `fetch_slots()`
- **Description**: Fetch available appointment slots for today and tomorrow.
- **Parameters**: None
- **Notes**: Returns availability for specific hours (10 AM, 2 PM, 5 PM, 6 PM, 7 PM, 8 PM, 9 PM) for the next 2 days.

### `book_appointment(start_time: str, num_people: int, name: Optional[str], contact_number: Optional[str], details: str)`
- **Description**: Book an appointment. If user is not identified yet, provide name and contact_number to identify and book in one step.
- **Parameters**:
    - `start_time` (str): The start time of the appointment (ISO format e.g. '2023-10-27T19:00:00').
    - `num_people` (int): The number of people for the reservation.
    - `name` (Optional[str]): The user's full name (if not already identified).
    - `contact_number` (Optional[str]): The user's contact number (if not already identified).
    - `details` (str): Additional details for the appointment (default: "General Reservation").
- **Notes**: Checks availability and only allows future reservations. Will suggest the next available slot if the requested one is unavailable or in the past.

### `retrieve_appointments()`
- **Description**: Retrieve past appointments for the current user.
- **Parameters**: None
- **Notes**: Requires the user to be identified first using `identify_user`.

### `cancel_appointment(appointment_id: str)`
- **Description**: Cancel an appointment.
- **Parameters**:
    - `appointment_id` (str): The ID of the appointment to cancel.

### `modify_appointment(appointment_id: str, new_start_time: Optional[str], new_num_people: Optional[int], new_details: Optional[str])`
- **Description**: Modify an existing appointment. User MUST be identified first. Shows current booking details before making changes.
- **Parameters**:
    - `appointment_id` (str): The ID of the appointment to modify.
    - `new_start_time` (Optional[str]): The new desired start time (ISO format).
    - `new_num_people` (Optional[int]): The new party size.
    - `new_details` (Optional[str]): Updated details or preferences.
- **Notes**: Requires at least one modification parameter. Will check availability for new times and only allows future dates.

### `update_booking_details(appointment_id: str, details: str)`
- **Description**: Update specific details like special occasions or dietary requirements for a booking.
- **Parameters**:
    - `appointment_id` (str): The ID of the appointment to update.
    - `details` (str): The special occasion or dietary requirements to add.

### `end_conversation()`
- **Description**: CALL THIS TOOL when the user is done, says goodbye, or wants to end the call. It triggers the final summary and closes the session gracefully.
- **Parameters**: None

## Limitations and Edge Cases