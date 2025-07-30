import os
import uuid
import time
import logging
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
from .voice_manager import VoiceManager, VoiceCloningRequest, Organization, Voice
from elevenlabs import set_api_key, generate, VoiceSettings, VoiceClone

app = FastAPI(title="Voice Management Service")
logger = logging.getLogger("voice-service")
logging.basicConfig(level=logging.INFO)

# Initialize voice manager
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "your_elevenlabs_api_key")
set_api_key(ELEVENLABS_API_KEY)
voice_manager = VoiceManager()

class OrganizationCreate(BaseModel):
    org_id: str
    org_name: str
    plan_type: str = "hybrid"
    greeting_message: str = "Hello! How can I assist you today?"
    lead_questions: List[dict] = []
    transfer_keywords: List[str] = ["human", "agent", "representative"]

class VoiceCloneRequest(BaseModel):
    name: str
    description: str = ""
    labels: List[str] = ["call-center", "organization-voice"]

class VoiceStatusResponse(BaseModel):
    voice_id: str
    status: str  # pending, processing, completed, failed
    progress: float  # 0.0 to 1.0
    organization_id: Optional[str] = None

@app.post("/organizations")
async def create_organization(org_data: OrganizationCreate):
    try:
        org = Organization(
            id=org_data.org_id,
            name=org_data.org_name,
            plan_type=org_data.plan_type,
            greeting_message=org_data.greeting_message,
            lead_questions=org_data.lead_questions,
            transfer_keywords=org_data.transfer_keywords
        )
        voice_manager.create_organization(org)
        return {"status": "created", "organization_id": org.id}
    except Exception as e:
        logger.error(f"Organization creation failed: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/organizations/{org_id}")
async def get_organization(org_id: str):
    org = voice_manager.get_organization(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    # Convert to API response format
    return {
        "org_id": org.id,
        "org_name": org.name,
        "plan_type": org.plan_type,
        "voice_id": org.voice_id,
        "fallback_voice_id": org.fallback_voice_id,
        "voice_settings": org.voice_settings,
        "greeting_message": org.greeting_message,
        "lead_questions": org.lead_questions,
        "transfer_keywords": org.transfer_keywords
    }

@app.put("/organizations/{org_id}")
async def update_organization(org_id: str, org_data: dict):
    try:
        updated_org = voice_manager.update_organization(org_id, org_data)
        return {"status": "updated", "organization": updated_org.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/organizations/{org_id}")
async def delete_organization(org_id: str):
    try:
        voice_manager.delete_organization(org_id)
        return {"status": "deleted", "organization_id": org_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/organizations/{org_id}/voice")
async def create_organization_voice(
    org_id: str,
    name: str = Form(...),
    description: str = Form("Organization voice"),
    files: List[UploadFile] = File(...)
):
    try:
        # Verify organization exists
        org = voice_manager.get_organization(org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        # Save audio files temporarily
        file_paths = []
        for file in files:
            file_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
            with open(file_path, "wb") as f:
                f.write(await file.read())
            file_paths.append(file_path)
        
        # Initiate voice cloning
        clone_request = VoiceCloningRequest(
            org_id=org_id,
            name=name,
            description=description,
            audio_files=file_paths
        )
        
        voice_id = voice_manager.clone_voice(clone_request)
        return {"status": "processing", "voice_id": voice_id}
    
    except Exception as e:
        logger.error(f"Voice cloning failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Voice cloning error: {str(e)}")

@app.get("/voices/{voice_id}/status")
async def get_voice_status(voice_id: str):
    voice = voice_manager.get_voice(voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")
    
    return VoiceStatusResponse(
        voice_id=voice_id,
        status=voice.status,
        progress=voice.progress,
        organization_id=voice.org_id
    )

@app.get("/voices")
async def list_voices(org_id: Optional[str] = None):
    if org_id:
        voices = voice_manager.get_voices_by_org(org_id)
    else:
        voices = voice_manager.list_voices()
    
    return [
        {
            "voice_id": v.voice_id,
            "name": v.name,
            "org_id": v.org_id,
            "status": v.status,
            "created_at": v.created_at
        } for v in voices
    ]

@app.post("/voices/generate")
async def generate_speech(
    text: str,
    voice_id: str,
    stability: float = 0.5,
    similarity_boost: float = 0.8
):
    try:
        voice = voice_manager.get_voice(voice_id)
        if not voice:
            raise HTTPException(status_code=404, detail="Voice not found")
        
        if voice.status != "ready":
            raise HTTPException(status_code=400, detail="Voice not ready")
        
        # Generate audio
        audio = generate(
            text=text,
            voice=VoiceClone(
                voice_id=voice_id,
                settings=VoiceSettings(
                    stability=stability,
                    similarity_boost=similarity_boost
                )
            )
        )
        
        # Return as base64
        audio_base64 = audio.decode("utf-8")
        return JSONResponse(content={"audio": audio_base64})
    
    except Exception as e:
        logger.error(f"Speech generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Speech generation error: {str(e)}")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "voice-service",
        "voices_managed": len(voice_manager.voices),
        "organizations": len(voice_manager.organizations)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)