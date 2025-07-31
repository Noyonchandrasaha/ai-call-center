import os
import logging
import json
import re
import asyncio
from typing import Dict, List, Optional
from pydantic import BaseModel

# Try to import providers
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

try:
    import anthropic
except ImportError:
    anthropic = None

logger = logging.getLogger("llm-engine")

class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4-turbo"
    api_key: Optional[str] = None
    max_tokens: int = 2000
    temperature: float = 0.7
    max_retries: int = 3
    timeout: int = 30

class LLMEngine:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.clients = {}
        
        # Initialize provider clients
        if config.provider == "openai" and AsyncOpenAI:
            if not config.api_key:
                config.api_key = os.getenv("OPENAI_API_KEY")
            if config.api_key:
                self.clients["openai"] = AsyncOpenAI(api_key=config.api_key)
            else:
                logger.warning("OpenAI API key not provided")
        
        elif config.provider == "anthropic" and anthropic:
            if not config.api_key:
                config.api_key = os.getenv("ANTHROPIC_API_KEY")
            if config.api_key:
                self.clients["anthropic"] = anthropic.AsyncAnthropic(api_key=config.api_key)
            else:
                logger.warning("Anthropic API key not provided")
        
        elif config.provider == "local":
            logger.info("Using local LLM mode")
        
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        session_id: str,
        org_id: str
    ) -> Dict[str, any]:
        """Generate response using configured LLM provider"""
        logger.info(f"Generating response for session {session_id}, org {org_id}")
        
        if self.config.provider == "openai" and "openai" in self.clients:
            return await self._generate_openai(messages)
        
        elif self.config.provider == "anthropic" and "anthropic" in self.clients:
            return await self._generate_anthropic(messages)
        
        elif self.config.provider == "local":
            return await self._generate_local(messages)
        
        else:
            raise RuntimeError("No valid LLM provider configured")
    
    async def _generate_openai(self, messages: List[Dict[str, str]]) -> Dict[str, any]:
        """Generate response using OpenAI API"""
        try:
            response = await self.clients["openai"].chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature
            )
            
            content = response.choices[0].message.content
            return {
                "content": content,
                "confidence": 0.95,  # OpenAI doesn't provide confidence
                "should_transfer": self._detect_transfer(content),
                "lead_answer": self._extract_lead_answer(content),
                "model": self.config.model,
                "tokens_used": response.usage.total_tokens
            }
        
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise
    
    async def _generate_anthropic(self, messages: List[Dict[str, str]]) -> Dict[str, any]:
        """Generate response using Anthropic API"""
        try:
            # Anthropic requires converting to their message format
            anthropic_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    # Anthropic doesn't support system messages in chat
                    continue
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            
            response = await self.clients["anthropic"].messages.create(
                model=self.config.model,
                messages=anthropic_messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature
            )
            
            content = response.content[0].text
            return {
                "content": content,
                "confidence": 0.93,  # Anthropic doesn't provide confidence
                "should_transfer": self._detect_transfer(content),
                "lead_answer": self._extract_lead_answer(content),
                "model": self.config.model,
                "tokens_used": response.usage.input_tokens + response.usage.output_tokens
            }
        
        except Exception as e:
            logger.error(f"Anthropic API error: {str(e)}")
            raise
    
    async def _generate_local(self, messages: List[Dict[str, str]]) -> Dict[str, any]:
        """Fallback to local logic when no provider is available"""
        # This would be replaced with actual local model integration
        # For now, use a simple rule-based response
        content = "I'm here to help. Please provide more details about your issue."
        return {
            "content": content,
            "confidence": 0.85,
            "should_transfer": False,
            "lead_answer": None,
            "model": "local-fallback",
            "tokens_used": 0
        }
    
    def _detect_transfer(self, content: str) -> bool:
        """Detect if the response suggests transferring to a human"""
        transfer_keywords = [
            "I can't help", "human agent", "speak to a representative",
            "contact support", "I'm unable", "escalate", "transfer"
        ]
        content_lower = content.lower()
        return any(keyword in content_lower for keyword in transfer_keywords)
    
    def _extract_lead_answer(self, content: str) -> Optional[Dict[str, str]]:
        """Extract structured lead answer from LLM response"""
        # Look for patterns like [ANSWER: value]
        pattern = r"\[ANSWER:\s*(.*?)\]"
        match = re.search(pattern, content)
        if match:
            return {"answer": match.group(1).strip()}
        return None