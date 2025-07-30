import os
import uuid
import time
import threading
import logging
import json
from elevenlabs import voices, clone, Voice
from typing import List, Dict, Optional
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("voice-manager")

class Organization(BaseModel):
    id: str
    name: str
    plan_type: str = "hybrid"  # human_only, ai_only, hybrid
    voice_id: Optional[str] = None
    fallback_voice_id: str = "default"
    voice_settings: Dict = {
        "stability": 0.5,
        "similarity_boost": 0.8
    }
    greeting_message: str = "Hello! How can I assist you today?"
    lead_questions: List[Dict] = []
    transfer_keywords: List[str] = ["human", "agent", "representative"]
    created_at: float = time.time()
    updated_at: float = time.time()

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
    created_at: float = time.time()
    updated_at: float = time.time()

class VoiceManager:
    def __init__(self):
        self.organizations = {}  # org_id: Organization
        self.voices = {}  # voice_id: VoiceStatus
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.default_voices = self._load_default_voices()
        
    def _load_default_voices(self):
        """Load default voices from ElevenLabs"""
        try:
            return {v.name: v for v in voices()}
        except Exception as e:
            logger.error(f"Failed to load default voices: {str(e)}")
            return {}
    
    def create_organization(self, org: Organization):
        if org.id in self.organizations:
            raise ValueError(f"Organization {org.id} already exists")
        self.organizations[org.id] = org
        logger.info(f"Created organization: {org.id}")
    
    def get_organization(self, org_id: str) -> Optional[Organization]:
        return self.organizations.get(org_id)
    
    def update_organization(self, org_id: str, update_data: dict) -> Organization:
        if org_id not in self.organizations:
            raise ValueError(f"Organization {org_id} not found")
        
        org = self.organizations[org_id]
        
        # Update fields
        for key, value in update_data.items():
            if hasattr(org, key):
                setattr(org, key, value)
        
        org.updated_at = time.time()
        logger.info(f"Updated organization: {org_id}")
        return org
    
    def delete_organization(self, org_id: str):
        if org_id not in self.organizations:
            raise ValueError(f"Organization {org_id} not found")
        del self.organizations[org_id]
        logger.info(f"Deleted organization: {org_id}")
    
    def clone_voice(self, request: VoiceCloningRequest) -> str:
        """Initiate voice cloning process"""
        voice_id = f"voice_{uuid.uuid4().hex[:8]}"
        
        # Create voice status object
        voice = VoiceStatus(
            voice_id=voice_id,
            org_id=request.org_id,
            name=request.name,
            description=request.description,
            status="pending"
        )
        self.voices[voice_id] = voice
        
        # Start cloning in background thread
        self.executor.submit(self._clone_voice_task, voice_id, request)
        
        # Update organization with new voice
        if request.org_id in self.organizations:
            org = self.organizations[request.org_id]
            org.voice_id = voice_id
            org.updated_at = time.time()
        
        return voice_id
    
    def _clone_voice_task(self, voice_id: str, request: VoiceCloningRequest):
        """Background task to handle voice cloning"""
        try:
            voice = self.voices[voice_id]
            voice.status = "cloning"
            voice.updated_at = time.time()
            
            logger.info(f"Starting voice cloning for {voice_id} with {len(request.audio_files)} files")
            
            # Update progress
            voice.progress = 0.1
            self.voices[voice_id] = voice
            
            # Clone voice using ElevenLabs API
            cloned_voice = clone(
                name=request.name,
                description=request.description,
                files=request.audio_files
            )
            
            # Update status
            voice.status = "ready"
            voice.progress = 1.0
            voice.updated_at = time.time()
            self.voices[voice_id] = voice
            
            logger.info(f"Voice cloning completed for {voice_id}")
            
            # Clean up audio files
            for file_path in request.audio_files:
                try:
                    os.remove(file_path)
                except:
                    pass
        
        except Exception as e:
            logger.error(f"Voice cloning failed for {voice_id}: {str(e)}")
            voice.status = "failed"
            voice.progress = 0.0
            voice.updated_at = time.time()
            self.voices[voice_id] = voice
    
    def get_voice(self, voice_id: str) -> Optional[VoiceStatus]:
        return self.voices.get(voice_id)
    
    def get_voices_by_org(self, org_id: str) -> List[VoiceStatus]:
        return [v for v in self.voices.values() if v.org_id == org_id]
    
    def list_voices(self) -> List[VoiceStatus]:
        return list(self.voices.values())
    
    def get_default_voice(self, name: str = "default") -> Optional[Voice]:
        return self.default_voices.get(name)