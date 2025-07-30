from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import Dict, Optional, List, Literal

class PlanType(str, Enum):
    HUMAN_ONLY = "human_only"
    AI_ONLY = "ai_only"
    HYBRID = "hybrid"

class AgentMode(str, Enum):
    AI = "ai"
    HUMAN = "human"
    TRANSFERRING = "transferring"

class TransferReason(str, Enum):
    USER_REQUEST = "user_request"
    AI_CONFIDENCE_LOW = "ai_confidence_low"
    ESCALATION = "escalation"
    COMPLEX_QUERY = "complex_query"

class VoiceStatus(str, Enum):
    READY = "ready"
    PROCESSING = "processing"
    FAILED = "failed"

class ConversationStage(str, Enum):
    GREETING = "greeting"
    MIDDLE = "middle"
    CLOSING = "closing"
    ENDED = "ended"

class LeadQuestion(BaseModel):
    question_id: str
    question_text: str
    required: bool = True
    order: int = 1
    trigger_condition: ConversationStage = ConversationStage.MIDDLE

class OrganizationConfig(BaseModel):
    org_id: str
    org_name: str
    plan_type: PlanType
    voice_id: str
    fallback_voice_id: str = "default-voice"
    voice_settings: Dict = {"stability": 0.5, "similarity_boost": 0.8}
    greeting_message: str = "Hello! How can I assist you today?"
    lead_questions: List[LeadQuestion] = []
    transfer_keywords: List[str] = ["human", "agent", "representative", "escalate"]
    ai_confidence_threshold: float = 0.7
    enable_document_retrieval: bool = True
    max_call_duration: int = 600
    subscription_active: bool = True

    @validator('lead_questions')
    def validate_lead_questions(cls, v):
        if any(q.trigger_condition == ConversationStage.GREETING for q in v):
            if not any(q.order == 1 for q in v):
                raise ValueError("Greeting questions must have order=1")
        return v

class SessionInfo(BaseModel):
    session_id: str
    org_id: str
    plan_type: PlanType
    agent_mode: AgentMode
    voice_id: str
    start_time: float
    last_interaction_time: float
    conversation_stage: ConversationStage = ConversationStage.GREETING
    human_agent_id: Optional[str] = None
    transfer_reason: Optional[TransferReason] = None
    lead_answers: Dict[str, str] = {}
    asked_questions: List[str] = []
    required_questions_pending: List[str] = []
    call_duration: float = 0.0

class LeadCapture(BaseModel):
    question_id: str
    question_text: str
    answer: str
    captured_at: float

class AudioMessage(BaseModel):
    audio: str = Field(..., regex=r"^[0-9a-fA-F]+$", max_length=10_000_000)

class VoiceStatusResponse(BaseModel):
    voice_id: str
    status: VoiceStatus
    progress: Optional[float] = None

class ServiceURLs:
    STT_SERVICE = "http://stt-service:8001"
    LLM_SERVICE = "http://llm-service:8002"
    TTS_SERVICE = "http://tts-service:8003"
    VOICE_SERVICE = "http://voice-service:8004"
    AGENT_SERVICE = "http://agent-service:8005"
    KNOWLEDGE_SERVICE = "http://knowledge-service:8006"
    LEADS_SERVICE = "http://leads-service:8007"
    BILLING_SERVICE = "http://billing-service:8008"