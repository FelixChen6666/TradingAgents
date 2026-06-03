"""Web API server configuration."""

from pydantic_settings import BaseSettings


class WebAPIConfig(BaseSettings):
    """Configuration for the TradingAgents Web API server."""

    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # How long to wait (seconds) for the client to send start_analysis
    ws_start_timeout: float = 300.0

    # How many recent messages/tool calls to retain
    buffer_max_length: int = 100

    model_config = {"env_prefix": "TA_WEB_"}


settings = WebAPIConfig()
