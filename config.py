# Configuration file for CallMi application

import os
from typing import Optional
from pathlib import Path

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path('.') / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded environment variables from {env_path}")
except ImportError:
    print("⚠️ python-dotenv not installed, using system environment variables only")

class Config:
    """Application configuration settings"""
    
    # Database settings
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./rooms.db")
    
    # Room management settings
    ROOM_CLEANUP_TIMEOUT_SECONDS: int = int(os.getenv("ROOM_CLEANUP_TIMEOUT_SECONDS", "300"))  # 15 seconds default
    ROOM_CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("ROOM_CLEANUP_INTERVAL_SECONDS", "60"))  # Check every 10 seconds
    
    # Auto-refresh intervals (in seconds)
    ROOM_LIST_REFRESH_INTERVAL: int = int(os.getenv("ROOM_LIST_REFRESH_INTERVAL", "30"))  # 30 seconds for room list
    USER_LIST_REFRESH_INTERVAL: int = int(os.getenv("USER_LIST_REFRESH_INTERVAL", "10"))   # 10 seconds for user list
    
    # WebSocket settings
    WEBSOCKET_TIMEOUT: int = int(os.getenv("WEBSOCKET_TIMEOUT", "60"))  # 60 seconds
    
    # Security settings
    ENABLE_PASSWORD_PROTECTION: bool = os.getenv("ENABLE_PASSWORD_PROTECTION", "true").lower() == "true"
    
    # Server settings
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Debug settings
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Global config instance
config = Config()

# Helper function to get config values with type conversion
def get_config_int(key: str, default: int) -> int:
    """Get integer configuration value with fallback to default"""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_config_bool(key: str, default: bool) -> bool:
    """Get boolean configuration value with fallback to default"""
    return os.getenv(key, str(default)).lower() == "true"

def get_config_str(key: str, default: str) -> str:
    """Get string configuration value with fallback to default"""
    return os.getenv(key, default)