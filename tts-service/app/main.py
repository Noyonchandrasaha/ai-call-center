import os
import logging
import base64
import time
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from elevenlabs import set_api_key, generate, Voice, VoiceSettings, voices
from .tts_engine import TTSEngine, VoiceCache

app = FastAPI(title="TTS Service")
logger = logging.getLogger("tts-service")
logging.basicConfig(level=logging.INFO)

# Initialize TTS engine
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "your_elevenlabs_api_key")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "Charlotte")
MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "1000"))
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"

tts_engine = TTSEngine(api_key=ELEVENLABS_API_KEY)
voice_cache = VoiceCache()

class SynthesizeRequest(BaseModel):
    text: str
    voice_id: str
    session_id: str
    stability: float = 0.5
    similarity_boost: float = 0.8
    style: float = 0.0
    use_speaker_boost: bool = True

class SynthesizeResponse(BaseModel):
    audio: str  # Base64 encoded audio
    voice_id: str
    processing_time: float
    cached: bool = False
    model_id: str
    character_count: int

@app.post("/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    start_time = time.time()
    
    try:
        # Validate input
        if len(request.text) > MAX_TEXT_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Text too long. Max {MAX_TEXT_LENGTH} characters allowed."
            )
        
        # Check cache first
        cache_key = f"{request.voice_id}_{request.text[:50]}"
        if CACHE_ENABLED:
            cached_audio = voice_cache.get(cache_key)
            if cached_audio:
                return SynthesizeResponse(
                    audio=cached_audio,
                    voice_id=request.voice_id,
                    processing_time=0.01,
                    cached=True,
                    model_id="cached",
                    character_count=len(request.text)
                )
        
        # Generate speech
        audio_data = await tts_engine.synthesize(
            text=request.text,
            voice_id=request.voice_id,
            stability=request.stability,
            similarity_boost=request.similarity_boost,
            style=request.style,
            use_speaker_boost=request.use_speaker_boost
        )
        
        # Convert to base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        # Cache the result
        if CACHE_ENABLED:
            voice_cache.set(cache_key, audio_base64)
        
        # Calculate processing time
        processing_time = time.time() - start_time
        
        return SynthesizeResponse(
            audio=audio_base64,
            voice_id=request.voice_id,
            processing_time=processing_time,
            model_id=tts_engine.current_model,
            character_count=len(request.text)
        )
    
    except Exception as e:
        logger.error(f"Speech synthesis failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Speech synthesis error: {str(e)}")

@app.get("/voices")
async def list_voices():
    try:
        return tts_engine.get_available_voices()
    except Exception as e:
        logger.error(f"Failed to list voices: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Voice listing error: {str(e)}")

@app.get("/voices/{voice_id}")
async def get_voice_details(voice_id: str):
    try:
        voice = tts_engine.get_voice_details(voice_id)
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        return voice
    except Exception as e:
        logger.error(f"Failed to get voice details: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Voice details error: {str(e)}")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "tts-service",
        "provider": "ElevenLabs",
        "default_voice": DEFAULT_VOICE,
        "voices_loaded": len(tts_engine.voice_map),
        "cache_enabled": CACHE_ENABLED,
        "cache_size": voice_cache.size()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)