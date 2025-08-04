import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from aiokafka import AIOKafkaProducer
from shared.redis_client import redis_pool
from shared.kafka_utils import get_kafka_producer
from shared.models import CallState

app = FastAPI()
KAFKA_AUDIO_TOPIC = "audio_stream"
ORG_CACHE_EXPIRE = 3600  # 1 hour

# WebSocket endpoint for Telnyx audio
@app.websocket("/call/{call_id}")
async def telnyx_websocket(websocket: WebSocket, call_id: str):
    await websocket.accept()
    redis = await redis_pool()
    producer = await get_kafka_producer()
    
    try:
        # Get call metadata from query params
        to_number = websocket.query_params.get("to")
        from_number = websocket.query_params.get("from")
        
        # Get organization configuration
        org_id = await get_org_id_from_number(to_number)
        org_config = await get_org_config(org_id)
        
        # Initialize call state
        call_state = CallState(
            call_id=call_id,
            org_id=org_id,
            to_number=to_number,
            from_number=from_number,
            plan_type=org_config["plan_type"]
        )
        await redis.setex(f"call:{call_id}", 3600, call_state.json())
        
        # Start audio processing tasks
        audio_task = asyncio.create_task(process_audio(websocket, producer, call_id))
        tts_task = asyncio.create_task(process_tts(websocket, call_id))
        
        await asyncio.gather(audio_task, tts_task)
        
    except WebSocketDisconnect:
        print(f"Call {call_id} disconnected")
    finally:
        await producer.stop()
        await redis.delete(f"call:{call_id}")

async def process_audio(websocket: WebSocket, producer: AIOKafkaProducer, call_id: str):
    """Forward audio chunks to Kafka"""
    while True:
        audio_chunk = await websocket.receive_bytes()
        await producer.send(
            topic=KAFKA_AUDIO_TOPIC,
            value=audio_chunk,
            key=call_id.encode()
        )

async def process_tts(websocket: WebSocket, call_id: str):
    """Send TTS audio back to Telnyx"""
    redis = await redis_pool()
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"tts_audio:{call_id}")
    
    async for message in pubsub.listen():
        if message["type"] == "message":
            await websocket.send_bytes(message["data"])

async def get_org_id_from_number(phone_number: str) -> str:
    """Resolve organization from phone number"""
    # Implementation would query database
    return "org_123"  # Simplified for example

async def get_org_config(org_id: str) -> dict:
    """Get organization configuration"""
    # Implementation would query database
    return {
        "plan_type": "ai_human",
        "voice_id": "voice_xyz",
        "lead_schema": {"property_type": "text", "budget": "number"}
    }