from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置结构"""
    ai_service_port: int = 8000
    grpc_port: int = 50051
    log_level: str = "INFO"
    
    # LLM Configuration
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    model_name: str = "gpt-3.5-turbo"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
