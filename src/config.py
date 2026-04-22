"""
Configurazione centralizzata tramite variabili d'ambiente.
Tutti i valori sensibili vanno in AWS Secrets Manager
e vengono iniettati come env vars al container ECS.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # --- Slack ---
    slack_bot_token: str = Field(..., env="SLACK_BOT_TOKEN")
    slack_signing_secret: str = Field(..., env="SLACK_SIGNING_SECRET")

    # --- DOS68K Chatbot Backend ---
    chatbot_base_url: str = Field(..., env="CHATBOT_BASE_URL")
    chatbot_api_key: str = Field(..., env="CHATBOT_API_KEY")

    # --- Logging ---
    log_health_checks: bool = Field(False, env="LOG_HEALTH_CHECKS")
    log_level: str = Field("INFO", env="LOG_LEVEL")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()