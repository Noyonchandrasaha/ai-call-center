from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime

class Organization(BaseModel):
    id: str
    name: str
    plan_type: str  # "ai_only", "human_only", "ai_human"
    created_at: datetime
    voice_id: Optional[str] = None
    lead_schema: Dict = {}

class CallState(BaseModel):
    call_id: str
    org_id: str
    to_number: str
    from_number: str
    plan_type: str
    status: str = "active"  # active, transferring, completed
    conversation: List[Dict] = []
    start_time: datetime = datetime.now()

class TranscriptMessage(BaseModel):
    call_id: str
    text: str
    is_final: bool
    speaker: Optional[str] = None
    timestamp: datetime = datetime.now()

class LLMResponse(BaseModel):
    content: str
    leads: List[Dict] = []

class TTSRequest(BaseModel):
    call_id: str
    text: str
    voice_id: str

class LeadData(BaseModel):
    call_id: str
    org_id: str
    data: Dict
    timestamp: datetime = datetime.now()

class VoiceProfile(BaseModel):
    id: str
    org_id: str
    voice_id: str
    name: str
    created_at: datetime = datetime.now()