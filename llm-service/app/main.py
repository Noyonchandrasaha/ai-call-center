import os
import logging
import json
import time
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .llm_engine import LLMEngine, LLMConfig
from .prompts import generate_system_prompt

app = FastAPI(title="LLM Service")
logger = logging.getLogger("llm-service")
logging.basicConfig(level=logging.INFO)

# Load configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4-turbo")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2000"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))

# Initialize LLM engine
llm_config = LLMConfig(
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
    api_key=os.getenv(f"{LLM_PROVIDER.upper()}_API_KEY"),
    max_tokens=MAX_TOKENS,
    temperature=TEMPERATURE
)
llm_engine = LLMEngine(config=llm_config)

class Document(BaseModel):
    title: str
    content: str
    relevance: float

class LeadQuestion(BaseModel):
    question_id: str
    question_text: str
    required: bool

class LLMRequest(BaseModel):
    query: str
    context: List[Dict[str, str]]
    session_id: str
    org_id: str
    documents: List[Document] = []
    lead_question: Optional[LeadQuestion] = None
    conversation_stage: str = "middle"
    remaining_questions: List[str] = []

class LLMResponse(BaseModel):
    response: str
    confidence: float
    should_transfer: bool
    lead_answer: Optional[Dict[str, str]] = None
    processing_time: float
    model: str
    tokens_used: int

@app.post("/generate")
async def generate(request: LLMRequest):
    start_time = time.time()
    
    try:
        # Generate system prompt
        system_prompt = generate_system_prompt(request)
        
        # Prepare messages for the LLM
        messages = [
            {"role": "system", "content": system_prompt},
            *request.context,
            {"role": "user", "content": request.query}
        ]
        
        # Generate response
        response = await llm_engine.generate_response(
            messages=messages,
            session_id=request.session_id,
            org_id=request.org_id
        )
        
        # Calculate processing time
        processing_time = time.time() - start_time
        
        return LLMResponse(
            response=response['content'],
            confidence=response['confidence'],
            should_transfer=response['should_transfer'],
            lead_answer=response.get('lead_answer'),
            processing_time=processing_time,
            model=response['model'],
            tokens_used=response['tokens_used']
        )
        
    except Exception as e:
        logger.error(f"LLM generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"LLM generation error: {str(e)}")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "llm-service",
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)