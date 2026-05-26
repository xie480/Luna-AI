import os

from app.config import Settings


def test_config_load() -> None:
    os.environ["SERVER_PORT"] = "9000"
    os.environ["LOG_LEVEL"] = "DEBUG"
    
    settings = Settings()
    
    assert settings.server_port == 9000
    assert settings.log_level == "DEBUG"
    
    # Clean up
    del os.environ["SERVER_PORT"]
    del os.environ["LOG_LEVEL"]
