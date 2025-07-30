import os
import time
import logging
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .stt_engine import transcribe_audio, AssemblyAIClient

app = FastAPI(title="STT Service")
logger = logging.getLogger("stt-service")
logging.basicConfig(level=logging.INFO)

# Initialize STT client
STT_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "your_assemblyai_api_key")
stt_client = AssemblyAIClient(api_key=STT_API_KEY)

class STTRequest(BaseModel):
    audio: str  # Base64 encoded audio data
    session_id: str
    audio_format: str = "wav"  # wav, mp3, etc.
    sample_rate: int = 16000
    language: str = "en"  # en, es, fr, etc.

class TranscriptionResponse(BaseModel):
    transcript: str
    confidence: float
    words: list
    processing_time: float
    session_id: str
    transcription_id: str

@app.post("/transcribe")
async def transcribe(request: STTRequest):
    start_time = time.time()
    
    try:
        # Generate unique ID for this transcription
        transcription_id = str(uuid.uuid4())
        logger.info(f"Starting transcription {transcription_id} for session {request.session_id}")
        
        # Transcribe audio
        result = await transcribe_audio(
            stt_client,
            request.audio,
            audio_format=request.audio_format,
            sample_rate=request.sample_rate,
            language=request.language
        )
        
        # Calculate processing time
        processing_time = time.time() - start_time
        
        logger.info(f"Completed transcription {transcription_id} in {processing_time:.2f}s")
        
        return TranscriptionResponse(
            transcript=result['text'],
            confidence=result['confidence'],
            words=result['words'],
            processing_time=processing_time,
            session_id=request.session_id,
            transcription_id=transcription_id
        )
    
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "stt-service",
        "stt_engine": "AssemblyAI"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)