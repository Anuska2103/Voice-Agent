"""
Application Configuration
All environment variables and settings in one place
"""

import os
from dotenv import load_dotenv
from logger import get_logger

LOGGER = get_logger(__name__)

# Load .env file
load_dotenv()


class Settings:
    """Application settings loaded from environment"""

    # ============================================
    # APP CONFIG
    # ============================================
    app_name: str = "Real Estate Voice Agent"
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    api_prefix: str = "/api/v1"

    # ============================================
    # MONGODB
    # ============================================
    mongo_uri: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    mongo_db_name: str = os.getenv("MONGO_DB_NAME", "real_estate")
    mongo_property_collection: str = os.getenv("MONGO_PROPERTY_COLLECTION", "properties")

    # ============================================
    # REDIS
    # ============================================
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")

    # ============================================
    # GOOGLE / GEMINI
    # ============================================
    google_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # ============================================
    # OPENWEATHERMAP
    # ============================================
    openweather_api_key: str = os.getenv("OPENWEATHER_API_KEY", "")

    # ============================================
    # DEEPGRAM (STT)
    # ============================================
    deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    deepgram_language: str = os.getenv("DEEPGRAM_LANGUAGE", "multi")

    # ============================================
    # ELEVENLABS (TTS)
    # ============================================
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")

    # ============================================
    # LIVEKIT
    # ============================================
    livekit_url: str = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
    livekit_api_key: str = os.getenv("LIVEKIT_API_KEY", "")
    livekit_api_secret: str = os.getenv("LIVEKIT_API_SECRET", "")
    join_access_key: str = os.getenv("JOIN_ACCESS_KEY", "")

    # ============================================
    # CORS
    # ============================================
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")

    def validate(self):
        """Check if required settings are present"""
        errors = []

        if not self.google_api_key:
            errors.append("GEMINI_API_KEY is not set")

        if not self.deepgram_api_key:
            errors.append("DEEPGRAM_API_KEY is not set")

        if not self.elevenlabs_api_key:
            errors.append("ELEVENLABS_API_KEY is not set")

        if not self.livekit_api_key or not self.livekit_api_secret:
            errors.append("LiveKit credentials not set")

        if not self.openweather_api_key:
            errors.append("OPENWEATHER_API_KEY is not set (weather tool will be disabled)")

        if errors:
            LOGGER.warning("Configuration warnings detected")
            for error in errors:
                LOGGER.warning("%s", error)

        return len(errors) == 0


# Create global settings instance
settings = Settings()

# Validate on import
if __name__ != "__main__":
    settings.validate()