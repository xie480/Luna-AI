import os

from app.config.settings import Settings


def test_config_load() -> None:
    os.environ["AI_SERVICE_PORT"] = "9000"
    os.environ["LOG_LEVEL"] = "DEBUG"

    settings = Settings()

    assert settings.ai_service_port == 9000
    assert settings.log_level == "DEBUG"

    # Clean up
    del os.environ["AI_SERVICE_PORT"]
    del os.environ["LOG_LEVEL"]
