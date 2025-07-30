import aiohttp
import base64
import logging
import asyncio
import time
from typing import Dict, Any

logger = logging.getLogger("stt-engine")

class AssemblyAIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.assemblyai.com/v2"
        self.headers = {
            "authorization": self.api_key,
            "content-type": "application/json"
        }
    
    async def upload_audio(self, audio_data: str) -> str:
        """Upload base64 audio data to AssemblyAI"""
        url = f"{self.base_url}/upload"
        payload = {"data": audio_data}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=self.headers) as response:
                if response.status != 200:
                    error = await response.text()
                    raise Exception(f"Upload failed: {response.status} - {error}")
                
                response_data = await response.json()
                return response_data['upload_url']
    
    async def submit_transcription(self, audio_url: str, config: Dict[str, Any]) -> str:
        """Submit transcription job"""
        url = f"{self.base_url}/transcript"
        payload = {
            "audio_url": audio_url,
            "speaker_labels": True,
            "word_boost": ["customer", "support", "help", "issue"],
            **config
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=self.headers) as response:
                if response.status != 200:
                    error = await response.text()
                    raise Exception(f"Submission failed: {response.status} - {error}")
                
                response_data = await response.json()
                return response_data['id']
    
    async def get_transcription(self, transcription_id: str) -> Dict[str, Any]:
        """Get transcription result"""
        url = f"{self.base_url}/transcript/{transcription_id}"
        
        while True:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status != 200:
                        error = await response.text()
                        raise Exception(f"Get transcription failed: {response.status} - {error}")
                    
                    response_data = await response.json()
                    status = response_data['status']
                    
                    if status == 'completed':
                        return response_data
                    elif status == 'failed':
                        raise Exception("Transcription failed")
                    else:
                        await asyncio.sleep(2)

async def transcribe_audio(
    client: AssemblyAIClient,
    audio_data: str,
    audio_format: str = "wav",
    sample_rate: int = 16000,
    language: str = "en"
) -> Dict[str, Any]:
    """Transcribe audio using AssemblyAI"""
    start_time = time.time()
    
    try:
        # Upload audio
        logger.info("Uploading audio data...")
        audio_url = await client.upload_audio(audio_data)
        
        # Submit transcription
        logger.info("Submitting transcription job...")
        transcription_id = await client.submit_transcription(audio_url, {
            "language_code": language,
            "audio_format": audio_format,
            "sample_rate": sample_rate
        })
        
        # Get transcription results
        logger.info("Waiting for transcription results...")
        result = await client.get_transcription(transcription_id)
        
        # Extract words with timestamps
        words = []
        for word in result.get('words', []):
            words.append({
                "text": word['text'],
                "start": word['start'],
                "end": word['end'],
                "confidence": word['confidence'],
                "speaker": word.get('speaker', 'A')
            })
        
        return {
            "text": result['text'],
            "confidence": result['confidence'],
            "words": words,
            "processing_time": time.time() - start_time
        }
    
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        raise