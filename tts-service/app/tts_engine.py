import os
import logging
import asyncio
from elevenlabs import set_api_key, generate, Voice, VoiceSettings, voices
from typing import Dict, Optional, List
import json

logger = logging.getLogger("tts-engine")

class TTSEngine:
    def __init__(self, api_key: str):
        set_api_key(api_key)
        self.api_key = api_key
        self.voice_map: Dict[str, Voice] = {}
        self.current_model = "eleven_multilingual_v2"
        self._load_voices()
    
    def _load_voices(self):
        """Load available voices from ElevenLabs API"""
        try:
            all_voices = voices()
            for voice in all_voices:
                self.voice_map[voice.voice_id] = voice
                self.voice_map[voice.name] = voice  # Also index by name
            
            logger.info(f"Loaded {len(self.voice_map)} voices from ElevenLabs")
        except Exception as e:
            logger.error(f"Failed to load voices: {str(e)}")
            # Fallback to default voices
            self.voice_map = {
                "Charlotte": Voice(
                    voice_id="XB0fDUnXU5powFXDhCwa",
                    name="Charlotte",
                    category="premade"
                ),
                "Domi": Voice(
                    voice_id="AZnzlk1XvdvUeBnXmlld",
                    name="Domi",
                    category="premade"
                )
            }
    
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        stability: float = 0.5,
        similarity_boost: float = 0.8,
        style: float = 0.0,
        use_speaker_boost: bool = True
    ) -> bytes:
        """Synthesize speech from text using ElevenLabs API"""
        try:
            # Get voice object
            voice = self.get_voice_details(voice_id)
            if not voice:
                raise ValueError(f"Voice {voice_id} not found")
            
            # Generate audio
            audio = generate(
                text=text,
                voice=voice,
                model=self.current_model,
                voice_settings=VoiceSettings(
                    stability=stability,
                    similarity_boost=similarity_boost,
                    style=style,
                    use_speaker_boost=use_speaker_boost
                )
            )
            
            return audio
        
        except Exception as e:
            logger.error(f"Synthesis failed for voice {voice_id}: {str(e)}")
            raise
    
    def get_available_voices(self) -> List[dict]:
        """Get list of available voices"""
        return [
            {
                "voice_id": voice.voice_id,
                "name": voice.name,
                "category": voice.category,
                "description": voice.description or "",
                "labels": voice.labels or {}
            }
            for voice in set(self.voice_map.values())
        ]
    
    def get_voice_details(self, voice_id: str) -> Optional[Voice]:
        """Get voice details by ID or name"""
        return self.voice_map.get(voice_id)


class VoiceCache:
    """Simple in-memory voice cache"""
    def __init__(self, max_size=1000):
        self.cache: Dict[str, str] = {}
        self.max_size = max_size
        self.access_order: List[str] = []
    
    def get(self, key: str) -> Optional[str]:
        """Get cached audio data"""
        if key in self.cache:
            # Move to end of access order (most recently used)
            self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        return None
    
    def set(self, key: str, audio: str):
        """Add audio to cache"""
        # If cache is full, remove least recently used item
        if len(self.cache) >= self.max_size:
            oldest_key = self.access_order.pop(0)
            del self.cache[oldest_key]
        
        self.cache[key] = audio
        self.access_order.append(key)
    
    def size(self) -> int:
        """Get current cache size"""
        return len(self.cache)