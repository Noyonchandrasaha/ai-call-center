import asyncio
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional, List

import aiohttp
import aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from .schemas import (
    PlanType, AgentMode, TransferReason, ConversationStage,
    OrganizationConfig, SessionInfo, LeadCapture, AudioMessage,
    VoiceStatusResponse, ServiceURLs
)
from .config import settings
from .utils import service_request, validate_audio, detect_conversation_stage

# Initialize logging
logger = logging.getLogger("api-gateway")
logging.basicConfig(level=logging.INFO)

# Global state
service_clients = {}
redis_pool = None
FALLBACK_VOICE_ID = "default-voice"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global service_clients, redis_pool
    
    # Create HTTP clients for services
    timeout = aiohttp.ClientTimeout(total=settings.SERVICE_TIMEOUT)
    service_clients = {
        'stt': aiohttp.ClientSession(timeout=timeout),
        'llm': aiohttp.ClientSession(timeout=timeout),
        'tts': aiohttp.ClientSession(timeout=timeout),
        'voice': aiohttp.ClientSession(timeout=timeout),
        'agent': aiohttp.ClientSession(timeout=timeout),
        'knowledge': aiohttp.ClientSession(timeout=timeout),
        'leads': aiohttp.ClientSession(timeout=timeout),
        'billing': aiohttp.ClientSession(timeout=timeout)
    }
    
    # Connect to Redis
    redis_pool = aioredis.from_url(
        settings.REDIS_URL,
        max_connections=20,
        decode_responses=False
    )
    
    try:
        await redis_pool.ping()
        logger.info("Connected to Redis successfully")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise RuntimeError("Failed to connect to Redis")
    
    yield
    
    # Cleanup on shutdown
    for client in service_clients.values():
        await client.close()
    if redis_pool:
        await redis_pool.close()

app = FastAPI(
    title="Enterprise Call Center AI Gateway",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.session_info: Dict[str, SessionInfo] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str, org_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        
        # Get organization config
        org_config = await self.get_org_config(org_id)
        if not org_config:
            await websocket.close(code=4004, reason="Organization not found")
            return False
            
        # Validate subscription
        if not await self.validate_subscription(org_id):
            await websocket.close(code=4003, reason="Subscription inactive")
            return False
            
        # Get effective voice ID
        voice_id = await self.get_effective_voice_id(org_config)
        
        # Create session
        session = SessionInfo(
            session_id=session_id,
            org_id=org_id,
            plan_type=org_config.plan_type,
            agent_mode=self._get_initial_agent_mode(org_config.plan_type),
            voice_id=voice_id,
            start_time=time.time(),
            last_interaction_time=time.time(),
            required_questions_pending=[
                q.question_id for q in org_config.lead_questions if q.required
            ]
        )
        
        self.session_info[session_id] = session
        await self.store_session(session)
        return True
    
    async def get_effective_voice_id(self, org_config: OrganizationConfig) -> str:
        """Check voice status and return fallback if needed"""
        status, response = await service_request(
            "GET", "voice", f"voices/{org_config.voice_id}/status",
            session=service_clients['voice']
        )
        
        if status == 200:
            voice_status = VoiceStatusResponse(**response)
            if voice_status.status == VoiceStatus.READY:
                return org_config.voice_id
                
        logger.warning(f"Voice {org_config.voice_id} not ready, using fallback")
        return org_config.fallback_voice_id or FALLBACK_VOICE_ID
    
    async def validate_subscription(self, org_id: str) -> bool:
        """Check if organization has active subscription"""
        status, response = await service_request(
            "GET", "billing", f"organizations/{org_id}/subscription",
            session=service_clients['billing']
        )
        return status == 200 and response.get("active", False)
    
    def _get_initial_agent_mode(self, plan_type: PlanType) -> AgentMode:
        if plan_type == PlanType.HUMAN_ONLY:
            return AgentMode.HUMAN
        elif plan_type == PlanType.AI_ONLY:
            return AgentMode.AI
        else:
            return AgentMode.AI
    
    async def store_session(self, session: SessionInfo):
        try:
            await redis_pool.setex(
                f"session:{session.session_id}",
                settings.SESSION_TTL,
                session.model_dump_json()
            )
        except Exception as e:
            logger.error(f"Redis store failed: {e}")
    
    async def update_session(self, session_id: str, **updates):
        if session_id in self.session_info:
            session = self.session_info[session_id]
            for key, value in updates.items():
                setattr(session, key, value)
            await self.store_session(session)
    
    async def get_org_config(self, org_id: str) -> Optional[OrganizationConfig]:
        """Get organization configuration from voice service"""
        try:
            status, response = await service_request(
                "GET", "voice", f"organizations/{org_id}",
                session=service_clients['voice']
            )
            if status == 200:
                return OrganizationConfig(**response)
            elif status == 404:
                logger.warning(f"Organization {org_id} not found")
                return None
            else:
                logger.error(f"Failed to get org config: HTTP {status}")
                return None
        except Exception as e:
            logger.error(f"Failed to get org config: {e}")
            return None

manager = ConnectionManager()

@app.websocket("/ws/{org_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    org_id: str,
    token: str = Query(..., description="JWT authentication token")
):
    # Authentication
    if not await verify_jwt_token(token, org_id):
        await websocket.close(code=4001, reason="Unauthorized")
        return
        
    session_id = str(uuid.uuid4())
    
    if not await manager.connect(websocket, session_id, org_id):
        return
        
    session = manager.session_info[session_id]
    org_config = await manager.get_org_config(org_id)
    
    try:
        # Initialize conversation context
        await redis_pool.setex(
            f"context:{session_id}", 
            settings.SESSION_TTL, 
            json.dumps([])
        )
        
        # Send welcome based on mode
        if session.agent_mode == AgentMode.AI:
            await send_welcome_message(websocket, session, org_config)
        elif session.agent_mode == AgentMode.HUMAN:
            await connect_to_human_agent(websocket, session)
        
        # Start background tasks
        heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
        monitoring_task = asyncio.create_task(monitor_session(websocket, session_id))
        
        # Main message loop
        while True:
            data = await websocket.receive_json()
            await manager.update_session(session_id, last_interaction_time=time.time())
            
            if data.get("type") == "audio":
                validate_audio(data["audio"])
                await route_audio_message(websocket, session, data["audio"], org_config)
            elif data.get("type") == "text":
                await route_text_message(websocket, session, data["text"], org_config)
            elif data.get("type") == "transfer_request":
                await handle_transfer_request(websocket, session, TransferReason.USER_REQUEST)
            elif data.get("type") == "end_call":
                await handle_call_end(websocket, session, org_config)
                
    except WebSocketDisconnect:
        logger.info(f"Session disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await send_error(websocket, session_id, "Connection error")
    finally:
        heartbeat_task.cancel()
        monitoring_task.cancel()
        manager.disconnect(session_id)
        await handle_call_end(websocket, session, org_config, forced=True)

async def send_heartbeat(websocket: WebSocket):
    """Keep connection alive with heartbeats"""
    while True:
        await asyncio.sleep(settings.HEARTBEAT_INTERVAL)
        try:
            await websocket.send_json({"type": "heartbeat", "timestamp": time.time()})
        except:
            break

async def monitor_session(websocket: WebSocket, session_id: str):
    """Monitor session for stage changes and timeouts"""
    while True:
        await asyncio.sleep(5)
        if session_id not in manager.session_info:
            break
            
        session = manager.session_info[session_id]
        duration = time.time() - session.start_time
        
        # Update call duration
        await manager.update_session(session_id, call_duration=duration)
        
        # Detect conversation stage changes
        new_stage = detect_conversation_stage(session, duration)
        if new_stage != session.conversation_stage:
            await manager.update_session(session_id, conversation_stage=new_stage)
            logger.info(f"Session {session_id} entered {new_stage} stage")
            
            # Handle stage-specific logic
            if new_stage == ConversationStage.CLOSING:
                await handle_closing_stage(websocket, session_id)

async def handle_closing_stage(websocket: WebSocket, session_id: str):
    """Handle actions required at closing stage"""
    session = manager.session_info[session_id]
    org_config = await manager.get_org_config(session.org_id)
    
    # Check for unanswered required questions
    unanswered = [
        q for q in org_config.lead_questions 
        if q.required and q.question_id in session.required_questions_pending
    ]
    
    if unanswered:
        await ask_pending_questions(websocket, session, unanswered)

async def ask_pending_questions(websocket: WebSocket, session: SessionInfo, questions: List[LeadQuestion]):
    """Ask unanswered required questions"""
    for question in sorted(questions, key=lambda q: q.order):
        await ask_lead_question(websocket, session, question)

async def ask_lead_question(websocket: WebSocket, session: SessionInfo, question: LeadQuestion):
    """Ask a specific lead question"""
    try:
        # Synthesize question audio
        status, tts_data = await service_request(
            "POST", "tts", "synthesize",
            {
                "text": question.question_text,
                "voice_id": session.voice_id,
                "session_id": session.session_id
            },
            session=service_clients['tts']
        )
        
        if status != 200:
            raise Exception("TTS failed")
        
        await websocket.send_json({
            "type": "lead_question",
            "session_id": session.session_id,
            "question_id": question.question_id,
            "text": question.question_text,
            "audio": tts_data.get("audio", ""),
            "required": question.required
        })
        
        # Add to asked questions
        await manager.update_session(
            session.session_id,
            asked_questions=[*session.asked_questions, question.question_id]
        )
        
    except Exception as e:
        logger.error(f"Failed to ask lead question: {e}")

async def process_ai_response(websocket: WebSocket, session: SessionInfo, user_input: str, 
                            org_config: OrganizationConfig, start_time: float, stt_data: Optional[Dict]):
    """Enhanced AI response processing with lead capture"""
    try:
        # Get conversation context
        context_data = await redis_pool.get(f"context:{session.session_id}")
        context = json.loads(context_data) if context_data else []
        
        # Get relevant documents
        documents = []
        if org_config.enable_document_retrieval:
            _, doc_response = await service_request(
                "POST", "knowledge", "search",
                {"org_id": session.org_id, "query": user_input, "limit": 3},
                session=service_clients['knowledge']
            )
            documents = doc_response.get("documents", [])
        
        # Get next lead question based on stage
        next_question = await get_next_lead_question(session, org_config)
        
        # Prepare LLM payload
        llm_payload = {
            "query": user_input,
            "context": context[-6:],
            "session_id": session.session_id,
            "org_id": session.org_id,
            "documents": documents,
            "lead_question": next_question.model_dump() if next_question else None,
            "conversation_stage": session.conversation_stage.value,
            "remaining_questions": session.required_questions_pending
        }
        
        # Call LLM service
        llm_status, llm_data = await service_request(
            "POST", "llm", "generate", llm_payload,
            session=service_clients['llm']
        )
        
        if llm_status != 200:
            raise Exception("LLM service error")
            
        ai_response = llm_data.get("response", "I'm sorry, please try again.")
        confidence = llm_data.get("confidence", 1.0)
        should_transfer = llm_data.get("should_transfer", False)
        lead_answer = llm_data.get("lead_answer")
        
        # Check for transfer conditions
        if session.plan_type == PlanType.HYBRID and (
            should_transfer or confidence < org_config.ai_confidence_threshold
        ):
            reason = TransferReason.AI_CONFIDENCE_LOW if confidence < org_config.ai_confidence_threshold else TransferReason.COMPLEX_QUERY
            await handle_transfer_request(websocket, session, reason)
            return
        
        # Capture lead answer
        if lead_answer and next_question:
            await capture_lead_answer(session, next_question, lead_answer["answer"])
        
        # Generate TTS
        tts_status, tts_data = await service_request(
            "POST", "tts", "synthesize",
            {
                "text": ai_response,
                "voice_id": session.voice_id,
                "session_id": session.session_id
            },
            session=service_clients['tts']
        )
        
        if tts_status != 200:
            raise Exception("TTS service error")
        
        # Update context
        context.extend([
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": ai_response}
        ])
        await redis_pool.setex(
            f"context:{session.session_id}", 
            settings.SESSION_TTL, 
            json.dumps(context)
        )
        
        # Prepare response
        response_data = {
            "type": "ai_response",
            "session_id": session.session_id,
            "transcript": user_input,
            "response": ai_response,
            "audio": tts_data.get("audio", ""),
            "voice_id": session.voice_id,
            "confidence": confidence,
            "processing_time": time.time() - start_time
        }
        
        if stt_data:
            response_data["metrics"] = {
                "stt_time": stt_data.get("processing_time", 0),
                "llm_time": llm_data.get("processing_time", 0),
                "tts_time": tts_data.get("processing_time", 0)
            }
        
        if lead_answer:
            response_data["lead_captured"] = {
                "question_id": next_question.question_id,
                "answer": lead_answer["answer"]
            }
        
        await websocket.send_json(response_data)
        
    except Exception as e:
        logger.error(f"AI processing error: {e}")
        await send_error(websocket, session.session_id, "AI service unavailable")

async def get_next_lead_question(session: SessionInfo, org_config: OrganizationConfig) -> Optional[LeadQuestion]:
    """Get next lead question considering conversation stage"""
    # Filter by stage and unanswered
    stage_questions = [
        q for q in org_config.lead_questions
        if q.trigger_condition == session.conversation_stage
        and q.question_id not in session.asked_questions
    ]
    
    # Prioritize required questions
    required = [q for q in stage_questions if q.required and q.question_id in session.required_questions_pending]
    if required:
        return min(required, key=lambda x: x.order)
    
    # Then non-required
    if stage_questions:
        return min(stage_questions, key=lambda x: x.order)
    
    return None

async def capture_lead_answer(session: SessionInfo, question: LeadQuestion, answer: str):
    """Capture and store lead answer"""
    # Update session
    new_answers = {**session.lead_answers, question.question_id: answer}
    new_asked = [*session.asked_questions, question.question_id]
    new_pending = [
        qid for qid in session.required_questions_pending 
        if qid != question.question_id
    ]
    
    await manager.update_session(
        session.session_id,
        lead_answers=new_answers,
        asked_questions=new_asked,
        required_questions_pending=new_pending
    )
    
    # Persist to leads service
    lead_capture = LeadCapture(
        question_id=question.question_id,
        question_text=question.question_text,
        answer=answer,
        captured_at=time.time()
    )
    
    await service_request(
        "POST", "leads", "capture",
        {
            "session_id": session.session_id,
            "org_id": session.org_id,
            "lead_capture": lead_capture.model_dump()
        },
        session=service_clients['leads']
    )

async def handle_transfer_request(websocket: WebSocket, session: SessionInfo, reason: TransferReason):
    """Transfer to human agent with full context"""
    if session.plan_type == PlanType.AI_ONLY:
        await send_error(websocket, session.session_id, "Transfer not available")
        return
        
    await manager.update_session(
        session.session_id,
        agent_mode=AgentMode.TRANSFERRING,
        transfer_reason=reason
    )
    
    # Get conversation context
    context_data = await redis_pool.get(f"context:{session.session_id}")
    context = json.loads(context_data) if context_data else []
    
    # Prepare transfer package
    transfer_package = {
        "session_id": session.session_id,
        "org_id": session.org_id,
        "reason": reason.value,
        "context": context[-10:],  # Last 10 exchanges
        "leads": session.lead_answers,
        "pending_questions": session.required_questions_pending
    }
    
    # Initiate transfer
    status, response = await service_request(
        "POST", "agent", "transfer",
        transfer_package,
        session=service_clients['agent']
    )
    
    if status == 200:
        agent_id = response.get("agent_id")
        await manager.update_session(
            session.session_id,
            agent_mode=AgentMode.HUMAN,
            human_agent_id=agent_id
        )
        
        await websocket.send_json({
            "type": "transfer_complete",
            "session_id": session.session_id,
            "agent_id": agent_id,
            "message": "Connected to human agent"
        })
    else:
        await manager.update_session(session.session_id, agent_mode=AgentMode.AI)
        await send_error(websocket, session.session_id, "Transfer failed")

async def handle_call_end(websocket: WebSocket, session: SessionInfo, 
                        org_config: OrganizationConfig, forced=False):
    """Handle call termination with lead validation"""
    # Check for unanswered required questions
    unanswered = [
        q for q in org_config.lead_questions 
        if q.required and q.question_id in session.required_questions_pending
    ]
    
    if unanswered and not forced:
        await ask_pending_questions(websocket, session, unanswered)
        return
        
    # Finalize lead capture
    if session.lead_answers:
        await service_request(
            "POST", "leads", "finalize",
            {
                "session_id": session.session_id,
                "org_id": session.org_id,
                "leads": session.lead_answers
            },
            session=service_clients['leads']
        )
    
    # Notify billing
    await service_request(
        "POST", "billing", "record-call",
        {
            "org_id": session.org_id,
            "session_id": session.session_id,
            "duration": session.call_duration,
            "agent_mode": session.agent_mode.value
        },
        session=service_clients['billing']
    )
    
    # Close session
    await websocket.send_json({
        "type": "call_end",
        "session_id": session.session_id,
        "duration": session.call_duration,
        "leads_captured": len(session.lead_answers)
    })

async def verify_jwt_token(token: str, org_id: str) -> bool:
    """Validate JWT token for organization access"""
    # In production, use a proper JWT validation library
    return True  # Simplified for example

# Health and monitoring endpoints
@app.get("/health")
async def health_check():
    redis_health = await check_redis_health()
    services_health = {
        "stt": await check_service_health("stt"),
        "tts": await check_service_health("tts"),
        "llm": await check_service_health("llm"),
        "voice": await check_service_health("voice"),
        "agent": await check_service_health("agent"),
        "knowledge": await check_service_health("knowledge")
    }
    
    return {
        "status": "healthy",
        "redis": redis_health,
        "services": services_health,
        "active_sessions": len(manager.active_connections)
    }

async def check_redis_health() -> dict:
    try:
        start = time.time()
        await redis_pool.ping()
        return {"status": "healthy", "latency": time.time() - start}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

async def check_service_health(service: str) -> dict:
    try:
        start = time.time()
        async with service_clients[service].get(f"{getattr(ServiceURLs, service.upper())}/health") as response:
            return {
                "status": "healthy" if response.status == 200 else "unhealthy",
                "http_status": response.status,
                "latency": time.time() - start
            }
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}

# Session management endpoints
@app.get("/sessions/{session_id}")
async def get_session_info(session_id: str):
    if session_id not in manager.session_info:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = manager.session_info[session_id]
    return {
        "session_id": session_id,
        "org_id": session.org_id,
        "plan_type": session.plan_type.value,
        "agent_mode": session.agent_mode.value,
        "duration": session.call_duration,
        "stage": session.conversation_stage.value,
        "leads_captured": len(session.lead_answers),
        "pending_questions": session.required_questions_pending
    }

@app.post("/sessions/{session_id}/transfer")
async def force_transfer(session_id: str, reason: TransferReason):
    if session_id not in manager.session_info:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = manager.session_info[session_id]
    if session.agent_mode != AgentMode.AI:
        raise HTTPException(status_code=400, detail="Invalid agent mode for transfer")
    
    await handle_transfer_request(None, session, reason)
    return {"status": "transfer_initiated"}