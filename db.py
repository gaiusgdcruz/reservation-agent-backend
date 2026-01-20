import os
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Check for Supabase credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False

class Database:
    def __init__(self):
        self.use_mock = False
        # Mock Data for Marriot Kochi
        self.opening_hour = 10  # 10 AM
        self.closing_hour = 22  # 10 PM
        self.tables = [
            {"id": "t1", "size": 2}, {"id": "t2", "size": 2}, {"id": "t3", "size": 2}, {"id": "t4", "size": 2}, {"id": "t5", "size": 2},
            {"id": "t6", "size": 4}, {"id": "t7", "size": 4}, {"id": "t8", "size": 4}, {"id": "t9", "size": 4}, {"id": "t10", "size": 4},
            {"id": "t11", "size": 4}, {"id": "t12", "size": 4}, {"id": "t13", "size": 4}, {"id": "t14", "size": 4}, {"id": "t15", "size": 4},
            {"id": "t16", "size": 6}, {"id": "t17", "size": 6},
            {"id": "t18", "size": 8}
        ]

        if not (SUPABASE_URL and SUPABASE_KEY and HAS_SUPABASE):
            print("Warning: Supabase credentials not found or sdk missing. Using mock database.")
            self.use_mock = True
            self.users = []
            self.appointments = []
            self.summaries = []  # New: Call summaries
        else:
            self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    async def save_summary(self, user_id: Optional[str], content: str, bookings: List[Dict], timestamp: str) -> Dict[str, Any]:
        """Save a call summary to the database."""
        summary = {
            "id": f"summary_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "user_id": user_id,
            "content": content,
            "bookings_snapshot": bookings,
            "timestamp": timestamp,
            "created_at": datetime.now().isoformat()
        }
        
        if self.use_mock:
            self.summaries.append(summary)
            print(f"Summary saved: {summary['id']}")
            return summary
        
        # Real Supabase
        res = self.client.table("summaries").insert(summary).execute()
        return res.data[0] if res.data else summary

    async def get_or_create_user(self, contact_number: str, name: Optional[str] = None) -> Dict[str, Any]:
        if self.use_mock:
            for user in self.users:
                if user["contact_number"] == contact_number:
                    if name:
                        user["name"] = name
                    return user
            
            new_user = {
                "id": f"user_{len(self.users) + 1}",
                "contact_number": contact_number,
                "name": name or "Unknown",
                "created_at": datetime.now().isoformat()
            }
            self.users.append(new_user)
            return new_user

        # Real Supabase implementation
        # Try to find user
        res = self.client.table("users").select("*").eq("contact_number", contact_number).execute()
        if res.data:
            user = res.data[0]
            if name:
                 self.client.table("users").update({"name": name}).eq("id", user["id"]).execute()
                 user["name"] = name # Return updated
            return user
        
        # Create user
        new_user = {
            "contact_number": contact_number,
            "name": name or "Unknown"
        }
        res = self.client.table("users").insert(new_user).execute()
        return res.data[0]

    async def create_appointment(self, user_id: str, start_time: str, num_people: int, details: str = "") -> Dict[str, Any]:
        # Parse start_time
        try:
            dt = datetime.fromisoformat(start_time)
        except ValueError:
            # Fallback/Mock just uses string if fail, but let's try to be robust
            pass

        final_details = f"Guests: {num_people}. {details}"

        if self.use_mock:
            appt = {
                "id": f"appt_{len(self.appointments) + 1}",
                "user_id": user_id,
                "start_time": start_time,
                "end_time": "TBD", 
                "status": "booked",
                "num_people": num_people,
                "details": final_details,
                "created_at": datetime.now().isoformat()
            }
            self.appointments.append(appt)
            return appt

        appt_data = {
            "user_id": user_id,
            "start_time": start_time,
            "end_time": start_time, # Should calculate real end time
            "status": "booked",
            "details": final_details
        }
        res = self.client.table("appointments").insert(appt_data).execute()
        return res.data[0]

    async def get_user_appointments(self, user_id: str) -> List[Dict[str, Any]]:
        if self.use_mock:
            return [a for a in self.appointments if a["user_id"] == user_id and a["status"] != "cancelled"]
        
        res = self.client.table("appointments").select("*").eq("user_id", user_id).neq("status", "cancelled").execute()
        return res.data

    async def cancel_appointment(self, appointment_id: str) -> bool:
        if self.use_mock:
            for appt in self.appointments:
                if appt["id"] == appointment_id:
                    appt["status"] = "cancelled"
                    return True
            return False
            
        res = self.client.table("appointments").update({"status": "cancelled"}).eq("id", appointment_id).execute()
        return len(res.data) > 0

    async def check_availability(self, start_time: str, num_people: int = 1) -> bool:
        """Check if a slot is available. One booking per time slot (appointment mode)."""
        try:
            # Handle possible 'Z' or offset strings
            dt_str = start_time.replace('Z', '+00:00')
            dt = datetime.fromisoformat(dt_str)
            
            # If naive, assume it's local time (server time)
            if dt.tzinfo is None:
                 now = datetime.now()
            else:
                 from datetime import timezone
                 now = datetime.now(timezone.utc)
            
            # Ensure it's in the future (allow 2 min buffer for clock skew)
            if dt.timestamp() < (now.timestamp() - 120):
                return False
                
            # Check hours
            if dt.hour < self.opening_hour or dt.hour >= self.closing_hour:
                return False
        except ValueError:
            return False

        # Check if ANY booking exists at this time slot
        if self.use_mock:
            existing = any(
                appt["start_time"] == start_time and appt["status"] == "booked"
                for appt in self.appointments
            )
        else:
            # Real Supabase query
            res = self.client.table("appointments").select("id").eq("start_time", start_time).eq("status", "booked").execute()
            existing = len(res.data) > 0 if res.data else False
        
        return not existing  # Available if NO booking exists

    async def get_next_available_slot(self, from_time: str) -> str:
        """Find the next available slot after the given time. Always in the future."""
        from datetime import timedelta
        
        now = datetime.now()
        try:
            dt = datetime.fromisoformat(from_time.replace('Z', '+00:00'))
        except ValueError:
            dt = now
        
        # We want slots after both 'from_time' and 'now'
        reference_time = max(dt, now)
        
        # Define available hours
        available_hours = [10, 14, 17, 18, 19]  # 10 AM, 2 PM, 5 PM, 6 PM, 7 PM
        
        # Check slots for the next 7 days
        for day_offset in range(7):
            check_date = reference_time.date() + timedelta(days=day_offset)
            for hour in available_hours:
                slot_time = datetime.combine(check_date, datetime.min.time().replace(hour=hour))
                
                # Skip if this slot is in the past or same as the reference time
                if slot_time <= reference_time:
                    continue
                
                slot_str = slot_time.strftime("%Y-%m-%dT%H:%M:%S")
                if await self.check_availability(slot_str):
                    return slot_str
        
        return None  # No slots available in next 7 days

    async def update_appointment(self, appointment_id: str, details: str) -> bool:
        """Update the details (preferences) of an appointment."""
        if self.use_mock:
            for appt in self.appointments:
                if appt["id"] == appointment_id:
                    appt["details"] = details
                    return True
            return False
        else:
            res = self.client.table("appointments").update({"details": details}).eq("id", appointment_id).execute()
            return len(res.data) > 0 if res.data else False

db = Database()
