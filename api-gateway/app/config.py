import os

class Settings:
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379")
    
    # Service URLs
    STT_SERVICE_URL: str = os.getenv("STT_SERVICE_URL", "http://stt-service:8001")
    TTS_SERVICE_URL: str = os.getenv("TTS_SERVICE_URL", "http://tts-service:8003")
    LLM_SERVICE_URL: str = os.getenv("LLM_SERVICE_URL", "http://llm-service:8002")
    VOICE_SERVICE_URL: str = os.getenv("VOICE_SERVICE_URL", "http://voice-service:8004")
    AGENT_SERVICE_URL: str = os.getenv("AGENT_SERVICE_URL", "http://agent-service:8005")
    KNOWLEDGE_SERVICE_URL: str = os.getenv("KNOWLEDGE_SERVICE_URL", "http://knowledge-service:8006")
    LEADS_SERVICE_URL: str = os.getenv("LEADS_SERVICE_URL", "http://leads-service:8007")
    BILLING_SERVICE_URL: str = os.getenv("BILLING_SERVICE_URL", "http://billing-service:8008")
    
    # Security
    SERVICE_API_KEY: str = os.getenv("SERVICE_API_KEY", "default-secret-key")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "default-jwt-secret")
    
    # SSL
    SSL_KEY_PATH: str = os.getenv("SSL_KEY_PATH", "")
    SSL_CERT_PATH: str = os.getenv("SSL_CERT_PATH", "")
    
    # Timeouts
    SERVICE_TIMEOUT: int = int(os.getenv("SERVICE_TIMEOUT", "30"))
    HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "15"))
    
    # Session
    SESSION_TTL: int = int(os.getenv("SESSION_TTL", "7200"))  # 2 hours

settings = Settings()