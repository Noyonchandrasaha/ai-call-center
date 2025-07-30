from pydantic import BaseModel
from typing import List, Dict, Optional

class Organization(BaseModel):
    id: str
    name: str
    plan_type: str = "hybrid"
    voice_id: Optional[str] = None
    fallback_voice_id: str = "default"
    voice_settings: Dict = {
        "stability": 0.5,
        "similarity_boost": 0.8
    }
    greeting_message: str = "Hello! How can I assist you today?"
    lead_questions: List[Dict] = []
    transfer_keywords: List[str] = ["human", "agent", "representative"]
    created_at: float = 0.0
    updated_at: float = 0.0

class VoiceCloningRequest(BaseModel):
    org_id: str
    name: str
    description: str
    audio_files: List[str]

class VoiceStatus(BaseModel):
    voice_id: str
    org_id: str
    name: str
    description: str
    status: str  # pending, cloning, ready, failed
    progress: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0