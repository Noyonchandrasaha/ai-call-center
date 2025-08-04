from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from shared.models import Organization, VoiceProfile

app = FastAPI()

class CreateOrgRequest(BaseModel):
    name: str
    plan_type: str  # "ai_only", "human_only", "ai_human"

class CreateVoiceRequest(BaseModel):
    name: str
    description: str

@app.post("/organizations")
async def create_organization(request: CreateOrgRequest):
    """Create a new organization"""
    org = Organization(
        name=request.name,
        plan_type=request.plan_type
    )
    # Save to database
    return {"id": org.id, "name": org.name}

@app.post("/organizations/{org_id}/voice")
async def create_custom_voice(
    org_id: str, 
    request: CreateVoiceRequest,
    samples: list[UploadFile] = File(...)
):
    """Create custom voice for organization"""
    # Upload samples to ElevenLabs
    voice_id = await elevenlabs_create_voice(
        name=f"{request.name} - {org_id}",
        description=request.description,
        files=[await file.read() for file in samples]
    )
    
    # Save voice profile
    voice = VoiceProfile(
        org_id=org_id,
        voice_id=voice_id,
        name=request.name
    )
    # Save to database
    return {"voice_id": voice_id}

@app.post("/organizations/{org_id}/documents")
async def upload_documents(
    org_id: str,
    files: list[UploadFile] = File(...)
):
    """Upload documents for organization"""
    for file in files:
        content = await file.read()
        # Process and store documents
        await store_document(org_id, file.filename, content)
    return {"status": "success"}

@app.post("/organizations/{org_id}/lead-questions")
async def set_lead_questions(
    org_id: str,
    questions: dict
):
    """Configure lead capture questions"""
    # Validate and save schema
    await save_lead_schema(org_id, questions)
    return {"status": "updated"}

async def elevenlabs_create_voice(name: str, description: str, files: list) -> str:
    """Create custom voice in ElevenLabs"""
    # Implementation using ElevenLabs API
    return "voice_xyz123"

# Helper functions for database operations would be implemented here