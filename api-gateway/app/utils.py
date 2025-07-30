import asyncio
import logging
import time
from typing import Dict, Optional, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential
from .config import settings
from .schemas import VoiceStatusResponse

logger = logging.getLogger("utils")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def service_request(method: str, service: str, endpoint: str, 
                         payload: dict = None, session=None) -> Tuple[int, dict]:
    """Generic service request with retry logic"""
    service_urls = {
        "stt": settings.STT_SERVICE_URL,
        "tts": settings.TTS_SERVICE_URL,
        "llm": settings.LLM_SERVICE_URL,
        "voice": settings.VOICE_SERVICE_URL,
        "agent": settings.AGENT_SERVICE_URL,
        "knowledge": settings.KNOWLEDGE_SERVICE_URL,
        "leads": settings.LEADS_SERVICE_URL,
        "billing": settings.BILLING_SERVICE_URL
    }
    
    url = f"{service_urls[service]}/{endpoint}"
    headers = {"X-API-KEY": settings.SERVICE_API_KEY}
    
    try:
        if method == "GET":
            async with session.get(url, headers=headers) as response:
                return response.status, await response.json()
        else:
            async with session.post(url, json=payload, headers=headers) as response:
                return response.status, await response.json()
    except Exception as e:
        logger.error(f"Service request failed: {service}/{endpoint} - {e}")
        return 503, {"error": "Service unavailable"}

def validate_audio(audio_hex: str):
    """Validate audio format and size"""
    if not re.match(r"^[0-9a-fA-F]+$", audio_hex):
        raise ValueError("Invalid audio format")
    if len(audio_hex) > 10_000_000:  # ~5 minutes of audio
        raise ValueError("Audio too large")

async def detect_conversation_stage(session, duration: float) -> ConversationStage:
    """Determine current conversation stage"""
    max_duration = 600  # Default 10 minutes
    
    if session.plan_type == PlanType.HUMAN_ONLY:
        max_duration = 1800  # 30 minutes for human calls
    
    if duration < 30:
        return ConversationStage.GREETING
    elif duration > max_duration * 0.8:
        return ConversationStage.CLOSING
    elif duration > max_duration:
        return ConversationStage.ENDED
    else:
        return ConversationStage.MIDDLE