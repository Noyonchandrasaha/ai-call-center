import asyncio
from elevenlabs.client import AsyncElevenLabs
from aiokafka import AIOKafkaConsumer
from shared.redis_client import redis_pool
from shared.kafka_utils import get_kafka_consumer
from shared.models import TTSRequest

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
KAFKA_TTS_TOPIC = "tts_requests"

client = AsyncElevenLabs(api_key=ELEVENLABS_API_KEY)

async def process_tts_requests():
    consumer = await get_kafka_consumer(KAFKA_TTS_TOPIC)
    redis = await redis_pool()
    
    async for msg in consumer:
        tts_request = TTSRequest.parse_raw(msg.value)
        call_id = msg.key.decode()
        
        # Generate speech
        audio = await client.generate(
            text=tts_request.text,
            voice_id=tts_request.voice_id,
            model="eleven_turbo_v2",
            stream=True
        )
        
        # Stream audio to Redis pubsub
        await publish_audio_chunks(call_id, audio)

async def publish_audio_chunks(call_id: str, audio_stream):
    """Stream audio chunks via Redis pubsub"""
    redis = await redis_pool()
    chunk_size = 4096  # 50ms chunks
    
    async for chunk in audio_stream:
        # Publish to call-specific channel
        await redis.publish(f"tts_audio:{call_id}", chunk)
        
        # Throttle to real-time speed
        await asyncio.sleep(0.05)

if __name__ == "__main__":
    asyncio.run(process_tts_requests())