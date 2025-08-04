import asyncio
import json
from openai import AsyncOpenAI
from aiokafka import AIOKafkaConsumer
from shared.redis_client import redis_pool
from shared.kafka_utils import get_kafka_consumer
from shared.models import TranscriptMessage, LLMResponse, LeadData

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KAFKA_TRANSCRIPT_TOPIC = "transcripts"
KAFKA_TTS_TOPIC = "tts_requests"
KAFKA_LEADS_TOPIC = "leads"

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

async def process_transcripts():
    consumer = await get_kafka_consumer(KAFKA_TRANSCRIPT_TOPIC)
    redis = await redis_pool()
    
    async for msg in consumer:
        transcript = TranscriptMessage.parse_raw(msg.value)
        call_id = msg.key.decode()
        
        # Get call state
        call_state = await redis.get(f"call:{call_id}")
        if not call_state: continue
        
        call_state = CallState.parse_raw(call_state)
        
        # Get organization config
        org_config = await get_org_config(call_state.org_id)
        
        # Build conversation history
        history = await build_conversation_history(call_id)
        
        # Generate AI response
        response = await generate_ai_response(
            transcript.text,
            history,
            org_config
        )
        
        # Handle human transfer
        if should_transfer_to_human(response, transcript.text):
            await transfer_to_human(call_id, call_state)
            continue
        
        # Save leads if detected
        if response.leads:
            await save_leads(call_id, response.leads)
        
        # Send response to TTS
        await send_to_tts(call_id, response.content, org_config["voice_id"])
        
        # Update conversation history
        await update_conversation_history(call_id, transcript.text, response.content)

async def generate_ai_response(
    user_input: str, 
    history: list, 
    org_config: dict
) -> LLMResponse:
    """Generate response using OpenAI with org-specific context"""
    messages = [
        {"role": "system", "content": build_system_prompt(org_config)}
    ] + history + [
        {"role": "user", "content": user_input}
    ]
    
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=300,
        response_format={"type": "json_object"},
        tools=[{
            "type": "function",
            "function": {
                "name": "extract_leads",
                "description": "Extract lead information based on conversation",
                "parameters": org_config["lead_schema"]
            }
        }]
    )
    
    # Parse structured response
    content = response.choices[0].message.content
    tool_calls = response.choices[0].message.tool_calls
    
    leads = []
    if tool_calls:
        for tool in tool_calls:
            if tool.function.name == "extract_leads":
                leads.append(LeadData.parse_raw(tool.function.arguments))
    
    return LLMResponse(content=content, leads=leads)

def build_system_prompt(org_config: dict) -> str:
    """Create system prompt with org-specific instructions"""
    return f"""
    You are {org_config['name']}'s customer service AI. 
    Respond conversationally using 1-2 short sentences.
    
    ORGANIZATION CONTEXT:
    {org_config['description']}
    
    LEAD CAPTURE INSTRUCTIONS:
    {json.dumps(org_config['lead_schema'])}
    
    HUMAN TRANSFER TRIGGERS:
    - Customer asks for human agent
    - Complex billing inquiries
    - Technical support issues
    """

async def transfer_to_human(call_id: str, call_state: CallState):
    """Transfer call to human agent"""
    redis = await redis_pool()
    
    # Find available agent
    agent_id = await find_available_agent(call_state.org_id)
    if not agent_id:
        # Fallback to voicemail
        await send_to_tts(call_id, "No agents available. Please leave a message.", "default")
        return
    
    # Update call state
    call_state.status = "transferring"
    await redis.setex(f"call:{call_id}", 3600, call_state.json())
    
    # Initiate transfer (Telnyx API call)
    await telnyx_transfer_call(call_id, agent_id)
    
    # Send transfer notification
    await send_to_tts(call_id, "Transferring you to an agent now.", call_state.voice_id)

async def telnyx_transfer_call(call_id: str, agent_id: str):
    """Initiate call transfer via Telnyx API"""
    # Implementation using Telnyx Python SDK
    pass

async def find_available_agent(org_id: str) -> str:
    """Find available agent from Redis sorted set"""
    redis = await redis_pool()
    return await redis.zpopmin(f"agents:{org_id}")

async def send_to_tts(call_id: str, text: str, voice_id: str):
    """Send text to TTS service via Kafka"""
    producer = await get_kafka_producer()
    message = TTSRequest(call_id=call_id, text=text, voice_id=voice_id)
    await producer.send(
        topic=KAFKA_TTS_TOPIC,
        value=message.json().encode(),
        key=call_id.encode()
    )

if __name__ == "__main__":
    asyncio.run(process_transcripts())