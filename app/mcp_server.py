import random
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ElderlyCareMcpServer")

# In-memory storage simulated database
medications_db = [
    {"id": 1, "name": "Aspirin", "dose": "81mg", "time": "08:00", "is_critical": True, "taken": False},
    {"id": 2, "name": "Vitamin D3", "dose": "2000 IU", "time": "12:00", "is_critical": False, "taken": False},
    {"id": 3, "name": "Lisinopril", "dose": "10mg", "time": "20:00", "is_critical": True, "taken": False}
]

wellness_logs = []

brain_teasers = {
    "easy": [
        {"question": "What word is spelled incorrectly in every dictionary?", "answer": "Incorrectly"},
        {"question": "I have keys but no locks. I have space but no room. You can enter but can't go outside. What am I?", "answer": "A keyboard"}
    ],
    "medium": [
        {"question": "The more of them you take, the more you leave behind. What are they?", "answer": "Footsteps"},
        {"question": "What has hands but cannot clap?", "answer": "A clock"}
    ],
    "hard": [
        {"question": "I speak without a mouth and hear without ears. I have no body, but I come alive with wind. What am I?", "answer": "An echo"},
        {"question": "A man is looking at a photograph of someone. His friend asks who it is. The man replies, 'Brothers and sisters, I have none. But that man's father is my father's son.' Who is in the photograph?", "answer": "His son"}
    ]
}

@mcp.tool()
def get_medications() -> dict:
    """Retrieves the list of active medications, dosages, and schedules for the user.

    Returns:
        A dictionary containing the list of active medications.
    """
    return {"status": "success", "medications": medications_db}

@mcp.tool()
def record_wellness_check(heart_rate: int, mood: str, pain_level: int) -> dict:
    """Logs the user's daily wellness vitals.

    Args:
        heart_rate: User's heart rate in beats per minute (bpm).
        mood: User's current emotional state or mood (e.g., Happy, Tired, Anxious).
        pain_level: User's self-reported pain level from 0 (no pain) to 10 (severe pain).

    Returns:
        A dictionary confirming the logging status.
    """
    log_entry = {
        "heart_rate": heart_rate,
        "mood": mood,
        "pain_level": pain_level
    }
    wellness_logs.append(log_entry)
    return {
        "status": "success",
        "message": "Daily wellness metrics recorded successfully.",
        "log": log_entry
    }

@mcp.tool()
def get_brain_teaser(difficulty: str) -> dict:
    """Retrieves a random cognitive puzzle or brain teaser of a specific difficulty.

    Args:
        difficulty: The difficulty level of the puzzle. Must be 'easy', 'medium', or 'hard'.

    Returns:
        A dictionary containing the question and answer.
    """
    diff = difficulty.lower()
    if diff not in brain_teasers:
        diff = "easy"
    teaser = random.choice(brain_teasers[diff])
    return {
        "status": "success",
        "difficulty": diff,
        "question": teaser["question"],
        "answer": teaser["answer"]
    }

@mcp.tool()
def schedule_medication(name: str, dose: str, time: str, is_critical: bool) -> dict:
    """Schedules a new medication reminder for the user.

    Args:
        name: The name of the medication.
        dose: The dosage (e.g., '10mg', '1 tablet').
        time: The scheduled time of day to take the medication (e.g., '08:00', '22:00').
        is_critical: Boolean indicating if this is a life-critical medication.

    Returns:
        A dictionary confirming the schedule status.
    """
    new_med = {
        "id": len(medications_db) + 1,
        "name": name,
        "dose": dose,
        "time": time,
        "is_critical": is_critical,
        "taken": False
    }
    medications_db.append(new_med)
    return {
        "status": "success",
        "message": f"Medication schedule for {name} ({dose}) at {time} created successfully.",
        "medication": new_med
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
