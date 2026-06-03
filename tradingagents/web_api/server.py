"""FastAPI application entry point for the TradingAgents Web API.

Usage:
    python -m tradingagents.web_api.server
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tradingagents.web_api.config import settings
from tradingagents.web_api.routers.health import router as health_router
from tradingagents.web_api.routers.config import router as config_router
from tradingagents.web_api.routers.ws import router as ws_router

app = FastAPI(
    title="TradingAgents Web API",
    version="0.1.0",
    description="Real-time WebSocket API for TradingAgents analysis",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(config_router)
app.include_router(ws_router)


def main():
    uvicorn.run(
        "tradingagents.web_api.server:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
