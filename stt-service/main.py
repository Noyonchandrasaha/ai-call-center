import asyncio
import assemblyai as aai
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from shared.redis_client import redis_pool
from shared.kafka_utils import get_kafka_consumer, get_kafka_producer
from shared.models import TranscriptMessage

KAFKA_AUDIO_TOPIC = "audio_stream"
KAFKA_TRANSCRIPT_TOPIC = "transcripts"

aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")

async def process_audio_stream():
    consumer = await get_kafka_consumer(KAFKA_AUDIO_TOPIC)
    producer = await get_kafka_producer()
    redis = await redis_pool()
    
    # Track active transcriber per call
    transcriber_map = {}
    
    async for msg in consumer:
        call_id = msg.key.decode()
        audio_chunk = msg.value
        
        # Get or create transcriber
        if call_id not in transcriber_map:
            transcriber = create_transcriber(call_id, producer)
            transcriber_map[call_id] = transcriber
            transcriber.connect()
        
        # Stream audio to AssemblyAI
        transcriber_map[call_id].stream(audio_chunk)

def create_transcriber(call_id: str, producer: AIOKafkaProducer):
    """Create AssemblyAI transcriber with custom handlers"""
    def on_data(transcript: aai.RealtimeTranscript):
        if not transcript.text: return
        
        # Create transcript message
        message = TranscriptMessage(
            call_id=call_id,
            text=transcript.text,
            is_final=transcript.message_type == "FinalTranscript"
        )
        
        # Send to Kafka
        asyncio.create_task(
            producer.send(
                topic=KAFKA_TRANSCRIPT_TOPIC,
                value=message.json().encode(),
                key=call_id.encode()
            )
        )
    
    def on_error(error: aai.RealtimeError):
        print(f"STT error for {call_id}: {error}")
    
    return aai.RealtimeTranscriber(
        sample_rate=16000,
        on_data=on_data,
        on_error=on_error,
        speaker_detection=True,
        extra_headers={"X-Call-ID": call_id}
    )

if __name__ == "__main__":
    asyncio.run(process_audio_stream())