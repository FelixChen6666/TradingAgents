"""Configuration endpoints — exposes available providers, models, and defaults."""

from fastapi import APIRouter

router = APIRouter(tags=["config"])


@router.get("/api/config/providers")
async def list_providers():
    """Return available LLM providers and their display names."""
    return {
        "providers": [
            {"id": "openai", "name": "OpenAI"},
            {"id": "anthropic", "name": "Anthropic"},
            {"id": "google", "name": "Google Gemini"},
            {"id": "xai", "name": "xAI (Grok)"},
            {"id": "deepseek", "name": "DeepSeek"},
            {"id": "qwen", "name": "Qwen (Global)"},
            {"id": "qwen-cn", "name": "Qwen (China)"},
            {"id": "glm", "name": "GLM (Z.AI)"},
            {"id": "glm-cn", "name": "GLM (BigModel)"},
            {"id": "minimax", "name": "MiniMax (Global)"},
            {"id": "minimax-cn", "name": "MiniMax (China)"},
            {"id": "ollama", "name": "Ollama (Local)"},
            {"id": "azure", "name": "Azure OpenAI"},
        ]
    }


@router.get("/api/config/models")
async def list_models(provider: str | None = None, mode: str | None = None):
    """Return model options, optionally filtered by provider and mode (quick/deep)."""
    from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

    if provider:
        models = MODEL_OPTIONS.get(provider.lower(), {})
        if mode:
            return {"models": models.get(mode, [])}
        return {"models": models}
    return {"providers": MODEL_OPTIONS}


@router.get("/api/config/defaults")
async def get_defaults():
    """Return default config (without secrets) for the frontend to pre-populate forms."""
    from tradingagents.default_config import DEFAULT_CONFIG

    safe_config = {k: v for k, v in DEFAULT_CONFIG.items() if k != "api_keys"}
    safe_config["analysts"] = ["market", "sentiment", "news", "fundamentals"]
    safe_config["output_language_options"] = [
        {"id": "English", "name": "English"},
        {"id": "Chinese", "name": "中文"},
        {"id": "Japanese", "name": "日本語"},
    ]
    safe_config["research_depth_options"] = [
        {"id": 1, "name": "Basic"},
        {"id": 3, "name": "Normal"},
        {"id": 5, "name": "Deep"},
    ]
    safe_config["asset_type_options"] = [
        {"id": "stock", "name": "Stock"},
        {"id": "crypto", "name": "Cryptocurrency"},
    ]
    return safe_config
