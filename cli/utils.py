import os
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import questionary
from dotenv import find_dotenv, set_key
from rich.console import Console

from cli.models import AnalystType, AssetType
from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.model_catalog import get_model_options

console = Console()

TICKER_INPUT_EXAMPLES = "SPY, 0700.HK, BTC-USD"

ANALYST_ORDER = [
    ("Market Analyst", AnalystType.MARKET),
    ("Sentiment Analyst", AnalystType.SOCIAL),
    ("News Analyst", AnalystType.NEWS),
    ("Fundamentals Analyst", AnalystType.FUNDAMENTALS),
]

CRYPTO_SUFFIXES = ("-USD", "-USDT", "-USDC", "-BTC", "-ETH")


def get_ticker() -> str:
    """Prompt the user to enter a ticker symbol, preserving exchange suffixes.

    Uses questionary.text (not typer.prompt, which strips trailing dot-suffixes
    like ``000404.SH`` on some shells) and validates the symbol charset so an
    obvious typo is caught before the run starts.
    """
    ticker = questionary.text(
        f"Enter ticker symbol (e.g. {TICKER_INPUT_EXAMPLES}):",
        validate=lambda x: (
            not x.strip()
            or (all(ch.isalnum() or ch in "._-^" for ch in x.strip()) and len(x.strip()) <= 32)
            or "Please enter a valid ticker symbol, e.g. AAPL, 000404.SZ, 0700.HK."
        ),
        style=questionary.Style(
            [
                ("text", "fg:green"),
                ("highlighted", "noinherit"),
            ]
        ),
    ).ask()

    if ticker is None:
        console.print("\n[red]No ticker symbol provided. Exiting...[/red]")
        exit(1)

    return normalize_ticker_symbol(ticker) if ticker.strip() else "SPY"


def normalize_ticker_symbol(ticker: str) -> str:
    """Normalize ticker input while preserving exchange suffixes."""
    return ticker.strip().upper()


def detect_asset_type(ticker: str) -> AssetType:
    normalized_ticker = ticker.strip().upper()
    if normalized_ticker.endswith(CRYPTO_SUFFIXES):
        return AssetType.CRYPTO
    return AssetType.STOCK


def filter_analysts_for_asset_type(
    analysts: List[AnalystType], asset_type: AssetType
) -> List[AnalystType]:
    if asset_type != AssetType.CRYPTO:
        return analysts
    return [
        analyst
        for analyst in analysts
        if analyst != AnalystType.FUNDAMENTALS
    ]


def get_analysis_date() -> str:
    """Prompt the user to enter a date in YYYY-MM-DD format."""
    import re
    from datetime import datetime

    def validate_date(date_str: str) -> bool:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    date = questionary.text(
        "Enter the analysis date (YYYY-MM-DD):",
        validate=lambda x: validate_date(x.strip())
        or "Please enter a valid date in YYYY-MM-DD format.",
        style=questionary.Style(
            [
                ("text", "fg:green"),
                ("highlighted", "noinherit"),
            ]
        ),
    ).ask()

    if not date:
        console.print("\n[red]No date provided. Exiting...[/red]")
        exit(1)

    return date.strip()


def select_analysts(asset_type: AssetType = AssetType.STOCK) -> List[AnalystType]:
    """Select analysts using an interactive checkbox."""
    available_analysts = filter_analysts_for_asset_type(
        [value for _, value in ANALYST_ORDER],
        asset_type,
    )
    choices = questionary.checkbox(
        "Select Your [Analysts Team]:",
        choices=[
            questionary.Choice(display, value=value)
            for display, value in ANALYST_ORDER
            if value in available_analysts
        ],
        instruction="\n- Press Space to select/unselect analysts\n- Press 'a' to select/unselect all\n- Press Enter when done",
        validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
        style=questionary.Style(
            [
                ("checkbox-selected", "fg:green"),
                ("selected", "fg:green noinherit"),
                ("highlighted", "noinherit"),
                ("pointer", "noinherit"),
            ]
        ),
    ).ask()

    if not choices:
        console.print("\n[red]No analysts selected. Exiting...[/red]")
        exit(1)

    return choices


def select_research_depth() -> int:
    """Select research depth using an interactive selection."""

    # Define research depth options with their corresponding values
    DEPTH_OPTIONS = [
        ("Shallow - Quick research, few debate and strategy discussion rounds", 1),
        ("Medium - Middle ground, moderate debate rounds and strategy discussion", 3),
        ("Deep - Comprehensive research, in depth debate and strategy discussion", 5),
    ]

    choice = questionary.select(
        "Select Your [Research Depth]:",
        choices=[
            questionary.Choice(display, value=value) for display, value in DEPTH_OPTIONS
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style(
            [
                ("selected", "fg:yellow noinherit"),
                ("highlighted", "fg:yellow noinherit"),
                ("pointer", "fg:yellow noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print("\n[red]No research depth selected. Exiting...[/red]")
        exit(1)

    return choice


def _fetch_openrouter_models() -> List[Tuple[str, str]]:
    """Fetch available models from the OpenRouter API."""
    import requests
    try:
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
        resp.raise_for_status()
        models = resp.json().get("data", [])
        return [(m.get("name") or m["id"], m["id"]) for m in models]
    except Exception as e:
        console.print(f"\n[yellow]Could not fetch OpenRouter models: {e}[/yellow]")
        return []


def select_openrouter_model() -> str:
    """Select an OpenRouter model from the newest available, or enter a custom ID."""
    models = _fetch_openrouter_models()

    choices = [questionary.Choice(name, value=mid) for name, mid in models[:5]]
    choices.append(questionary.Choice("Custom model ID", value="custom"))

    choice = questionary.select(
        "Select OpenRouter Model (latest available):",
        choices=choices,
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style([
            ("selected", "fg:magenta noinherit"),
            ("highlighted", "fg:magenta noinherit"),
            ("pointer", "fg:magenta noinherit"),
        ]),
    ).ask()

    if choice is None or choice == "custom":
        return questionary.text(
            "Enter OpenRouter model ID (e.g. google/gemma-4-26b-a4b-it):",
            validate=lambda x: len(x.strip()) > 0 or "Please enter a model ID.",
        ).ask().strip()

    return choice


def _prompt_custom_model_id() -> str:
    """Prompt user to type a custom model ID."""
    return questionary.text(
        "Enter model ID:",
        validate=lambda x: len(x.strip()) > 0 or "Please enter a model ID.",
    ).ask().strip()


def _select_model(provider: str, mode: str) -> str:
    """Select a model for the given provider and mode (quick/deep)."""
    if provider.lower() == "openrouter":
        return select_openrouter_model()

    if provider.lower() == "azure":
        return questionary.text(
            f"Enter Azure deployment name ({mode}-thinking):",
            validate=lambda x: len(x.strip()) > 0 or "Please enter a deployment name.",
        ).ask().strip()

    choice = questionary.select(
        f"Select Your [{mode.title()}-Thinking LLM Engine]:",
        choices=[
            questionary.Choice(display, value=value)
            for display, value in get_model_options(provider, mode)
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style(
            [
                ("selected", "fg:magenta noinherit"),
                ("highlighted", "fg:magenta noinherit"),
                ("pointer", "fg:magenta noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print(f"\n[red]No {mode} thinking llm engine selected. Exiting...[/red]")
        exit(1)

    if choice == "custom":
        return _prompt_custom_model_id()

    return choice


def select_shallow_thinking_agent(provider) -> str:
    """Select shallow thinking llm engine using an interactive selection."""
    return _select_model(provider, "quick")


def select_deep_thinking_agent(provider) -> str:
    """Select deep thinking llm engine using an interactive selection."""
    return _select_model(provider, "deep")

def _llm_provider_table() -> list[tuple[str, str, str | None]]:
    """(display_name, provider_key, base_url) for every supported provider.

    Shared by the interactive picker and by env-driven configuration so an
    env-set provider resolves to the same default endpoint the menu uses.
    Ollama users can point at a remote ollama-serve via OLLAMA_BASE_URL
    (convention from the broader Ollama ecosystem); falls back to the
    localhost default when unset.
    """
    ollama_url = os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
    return [
        ("OpenAI", "openai", "https://api.openai.com/v1"),
        ("Google", "google", None),
        ("Anthropic", "anthropic", "https://api.anthropic.com/"),
        ("xAI", "xai", "https://api.x.ai/v1"),
        ("DeepSeek", "deepseek", "https://api.deepseek.com"),
        ("Qwen", "qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        ("GLM", "glm", "https://open.bigmodel.cn/api/paas/v4/"),
        ("MiniMax", "minimax", "https://api.minimax.io/v1"),
        ("OpenRouter", "openrouter", "https://openrouter.ai/api/v1"),
        ("Azure OpenAI", "azure", None),
        ("Ollama", "ollama", ollama_url),
    ]


def provider_default_url(provider_key: str) -> str | None:
    """Return the default backend URL for a provider key, or None if unknown."""
    key = provider_key.lower()
    for _, pk, url in _llm_provider_table():
        if pk == key:
            return url
    return None


def select_llm_provider() -> tuple[str, str | None]:
    """Select the LLM provider and its API endpoint."""
    PROVIDERS = _llm_provider_table()

    choice = questionary.select(
        "Select your LLM Provider:",
        choices=[
            questionary.Choice(display, value=(provider_key, url))
            for display, provider_key, url in PROVIDERS
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style(
            [
                ("selected", "fg:magenta noinherit"),
                ("highlighted", "fg:magenta noinherit"),
                ("pointer", "fg:magenta noinherit"),
            ]
        ),
    ).ask()
    
    if choice is None:
        console.print("\n[red]No LLM provider selected. Exiting...[/red]")
        exit(1)

    provider, url = choice
    return provider, url


def ask_openai_reasoning_effort() -> str:
    """Ask for OpenAI reasoning effort level."""
    choices = [
        questionary.Choice("Medium (Default)", "medium"),
        questionary.Choice("High (More thorough)", "high"),
        questionary.Choice("Low (Faster)", "low"),
    ]
    return questionary.select(
        "Select Reasoning Effort:",
        choices=choices,
        style=questionary.Style([
            ("selected", "fg:cyan noinherit"),
            ("highlighted", "fg:cyan noinherit"),
            ("pointer", "fg:cyan noinherit"),
        ]),
    ).ask()


def ask_anthropic_effort() -> str | None:
    """Ask for Anthropic effort level.

    Controls token usage and response thoroughness on Claude 4.5 / 4.6 / 4.7
    models. The API also accepts "max"; we expose low/medium/high as the
    common selection range.
    """
    return questionary.select(
        "Select Effort Level:",
        choices=[
            questionary.Choice("High (recommended)", "high"),
            questionary.Choice("Medium (balanced)", "medium"),
            questionary.Choice("Low (faster, cheaper)", "low"),
        ],
        style=questionary.Style([
            ("selected", "fg:cyan noinherit"),
            ("highlighted", "fg:cyan noinherit"),
            ("pointer", "fg:cyan noinherit"),
        ]),
    ).ask()


def ask_gemini_thinking_config() -> str | None:
    """Ask for Gemini thinking configuration.

    Returns thinking_level: "high" or "minimal".
    Client maps to appropriate API param based on model series.
    """
    return questionary.select(
        "Select Thinking Mode:",
        choices=[
            questionary.Choice("Enable Thinking (recommended)", "high"),
            questionary.Choice("Minimal/Disable Thinking", "minimal"),
        ],
        style=questionary.Style([
            ("selected", "fg:green noinherit"),
            ("highlighted", "fg:green noinherit"),
            ("pointer", "fg:green noinherit"),
        ]),
    ).ask()


def ask_glm_region() -> tuple[str, str]:
    """Ask which GLM platform (Z.AI international vs BigModel China) to use.

    Zhipu serves the same GLM models under two brands with separate
    accounts; keys aren't interchangeable. Returns (provider_key, backend_url).
    """
    return questionary.select(
        "Select GLM platform:",
        choices=[
            questionary.Choice(
                "Z.AI — api.z.ai (international, uses ZHIPU_API_KEY)",
                value=("glm", "https://api.z.ai/api/paas/v4/"),
            ),
            questionary.Choice(
                "BigModel — open.bigmodel.cn (China, uses ZHIPU_CN_API_KEY)",
                value=("glm-cn", "https://open.bigmodel.cn/api/paas/v4/"),
            ),
        ],
        style=questionary.Style([
            ("selected", "fg:cyan noinherit"),
            ("highlighted", "fg:cyan noinherit"),
            ("pointer", "fg:cyan noinherit"),
        ]),
    ).ask()


def ask_qwen_region() -> tuple[str, str]:
    """Ask which Qwen region (international vs China) to use.

    Alibaba DashScope exposes two endpoints with separate accounts —
    a key from one region does NOT authenticate against the other
    (fixes #758). Returns (provider_key, backend_url).
    """
    return questionary.select(
        "Select Qwen region:",
        choices=[
            questionary.Choice(
                "International — dashscope-intl.aliyuncs.com (uses DASHSCOPE_API_KEY)",
                value=("qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            ),
            questionary.Choice(
                "China — dashscope.aliyuncs.com (uses DASHSCOPE_CN_API_KEY)",
                value=("qwen-cn", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ),
        ],
        style=questionary.Style([
            ("selected", "fg:cyan noinherit"),
            ("highlighted", "fg:cyan noinherit"),
            ("pointer", "fg:cyan noinherit"),
        ]),
    ).ask()


def ask_minimax_region() -> tuple[str, str]:
    """Ask which MiniMax region (global vs China) to use.

    MiniMax exposes two endpoints with separate accounts — a key from
    one region does NOT authenticate against the other. Returns
    (provider_key, backend_url).
    """
    return questionary.select(
        "Select MiniMax region:",
        choices=[
            questionary.Choice(
                "Global — api.minimax.io (uses MINIMAX_API_KEY)",
                value=("minimax", "https://api.minimax.io/v1"),
            ),
            questionary.Choice(
                "China — api.minimaxi.com (uses MINIMAX_CN_API_KEY)",
                value=("minimax-cn", "https://api.minimaxi.com/v1"),
            ),
        ],
        style=questionary.Style([
            ("selected", "fg:cyan noinherit"),
            ("highlighted", "fg:cyan noinherit"),
            ("pointer", "fg:cyan noinherit"),
        ]),
    ).ask()


def confirm_ollama_endpoint(url: str) -> None:
    """Show the resolved Ollama endpoint after provider selection.

    Surfaces three things the user benefits from seeing before model
    selection: which URL we'll actually hit, where it came from
    (\`OLLAMA_BASE_URL\` vs default), and a soft warning if the URL is
    missing the scheme/port that ollama-serve expects. The warning is
    advisory only — we don't reject malformed input, since the user may
    be doing something deliberately unusual (e.g. a reverse-proxy path).
    """
    from_env = os.environ.get("OLLAMA_BASE_URL")
    origin = " (from OLLAMA_BASE_URL)" if from_env and from_env == url else ""
    console.print(f"[green]✓ Using Ollama at {url}{origin}[/green]")

    if not url.startswith(("http://", "https://")):
        console.print(
            f"[yellow]Note: {url!r} is missing a scheme. "
            f"Ollama-serve typically expects a URL like "
            f"http://<host>:11434/v1.[/yellow]"
        )
    elif ":11434" not in url and "://localhost" not in url and "://127.0.0.1" not in url:
        # Soft hint when the port differs from the ollama-serve default
        # and the host isn't local (where users sometimes proxy on :80).
        console.print(
            f"[yellow]Note: {url!r} doesn't include port 11434. "
            f"Make sure your remote ollama-serve listens on the port "
            f"shown above.[/yellow]"
        )


def ensure_api_key(provider: str) -> Optional[str]:
    """Make sure the API key for `provider` is available in the environment.

    If the env var is already set, returns its value untouched. Otherwise
    interactively prompts the user, persists the value to the project's
    .env file via python-dotenv's set_key (creating .env if needed), and
    exports it into os.environ so the current process picks it up.

    Returns None for providers that do not require a key (e.g. ollama)
    and for providers not found in the canonical mapping.
    """
    env_var = get_api_key_env(provider)
    if env_var is None:
        return None  # ollama / unknown — no key check possible

    existing = os.environ.get(env_var)
    if existing:
        return existing

    console.print(
        f"\n[yellow]{env_var} is not set in your environment.[/yellow]"
    )
    key = questionary.password(
        f"Paste your {env_var} (will be saved to .env):",
        style=questionary.Style([
            ("text", "fg:cyan"),
            ("highlighted", "noinherit"),
        ]),
    ).ask()
    if not key:
        console.print(
            f"[red]Skipped. API calls will fail until {env_var} is set.[/red]"
        )
        return None

    env_path = find_dotenv(usecwd=True) or str(Path.cwd() / ".env")
    Path(env_path).touch(exist_ok=True)
    set_key(env_path, env_var, key)
    os.environ[env_var] = key
    console.print(f"[green]Saved {env_var} to {env_path}[/green]")
    return key


def ask_output_language() -> str:
    """Ask for report output language."""
    choice = questionary.select(
        "Select Output Language:",
        choices=[
            questionary.Choice("English (default)", "English"),
            questionary.Choice("Chinese (中文)", "Chinese"),
            questionary.Choice("Japanese (日本語)", "Japanese"),
            questionary.Choice("Korean (한국어)", "Korean"),
            questionary.Choice("Hindi (हिन्दी)", "Hindi"),
            questionary.Choice("Spanish (Español)", "Spanish"),
            questionary.Choice("Portuguese (Português)", "Portuguese"),
            questionary.Choice("French (Français)", "French"),
            questionary.Choice("German (Deutsch)", "German"),
            questionary.Choice("Arabic (العربية)", "Arabic"),
            questionary.Choice("Russian (Русский)", "Russian"),
            questionary.Choice("Custom language", "custom"),
        ],
        style=questionary.Style([
            ("selected", "fg:yellow noinherit"),
            ("highlighted", "fg:yellow noinherit"),
            ("pointer", "fg:yellow noinherit"),
        ]),
    ).ask()

    if choice == "custom":
        return questionary.text(
            "Enter language name (e.g. Turkish, Vietnamese, Thai, Indonesian):",
            validate=lambda x: len(x.strip()) > 0 or "Please enter a language name.",
        ).ask().strip()

    return choice


# ---------------------------------------------------------------------------
# Data vendor configuration
# ---------------------------------------------------------------------------

# Market presets: maps a user-facing choice to data_vendor overrides.
# Keys match DEFAULT_CONFIG["data_vendors"]. Only categories whose vendor
# differs from the system defaults need to be listed.
_DATA_PRESETS: Dict[str, Dict[str, str]] = {
    "preset_us": {
        "label": "US Markets (Standard)",
        "description": "Yahoo Finance for stock data, fundamentals, and news",
        # All yfinance defaults — empty dict means no overrides
        "overrides": {},
    },
    "preset_china": {
        "label": "China A-Shares",
        "description": "AKShare for OHLCV/fundamentals, East Money for news",
        "overrides": {
            "core_stock_apis": "akshare",
            "fundamental_data": "akshare",
            "news_data": "eastmoney",
            "social_sentiment": "all",
        },
    },
    "preset_hk": {
        "label": "Hong Kong Stocks",
        "description": "Yahoo Finance for OHLCV, Sina Finance for news",
        "overrides": {
            "news_data": "sina_finance",
            "social_sentiment": "all",
        },
    },
    "preset_global": {
        "label": "Global / Diversified",
        "description": "Yahoo Finance globally, East Money for China news coverage",
        "overrides": {
            "news_data": "eastmoney",
            "social_sentiment": "all",
        },
    },
    "custom": {
        "label": "Custom — configure each category",
        "description": "Individually pick vendors per data category",
        "overrides": "__custom__",
    },
}


def select_data_vendors(
    asset_type: AssetType = AssetType.STOCK,
) -> Dict[str, str]:
    """Interactively configure data vendors per category.

    Presents a preset picker first so most users just pick their market
    and move on. Selecting "Custom" drops into per-category selects.

    Returns:
        A dict mapping category keys (e.g. ``"news_data"``) to the
        chosen vendor name. Only non-default choices are included so the
        caller can merge only what changed. Returns an empty dict when
        the user keeps all defaults.
    """
    choices = []
    for key, cfg in _DATA_PRESETS.items():
        choices.append(
            questionary.Choice(f"{cfg['label']} — {cfg['description']}", value=key)
        )

    profile = questionary.select(
        "Select Data Vendor Profile:",
        choices=choices,
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style([
            ("selected", "fg:cyan noinherit"),
            ("highlighted", "fg:cyan noinherit"),
            ("pointer", "fg:cyan noinherit"),
        ]),
    ).ask()

    if profile is None or profile == "preset_us":
        return {}

    if profile != "custom":
        return _DATA_PRESETS[profile]["overrides"].copy()

    # Custom: show per-category selects for multi-vendor categories
    _CATEGORIES: Dict[str, Dict[str, str]] = {
        "core_stock_apis": {
            "label": "Stock Price Data (OHLCV)",
            "options": {
                "yfinance": "Yahoo Finance (default, no API key needed)",
                "alpha_vantage": "Alpha Vantage (free API key required)",
                "akshare": "AKShare (China markets, free)",
            },
            "default": "yfinance",
        },
        "technical_indicators": {
            "label": "Technical Indicators (SMA, RSI, MACD…)",
            "options": {
                "yfinance": "Yahoo Finance (default, no API key needed)",
                "alpha_vantage": "Alpha Vantage (free API key required)",
            },
            "default": "yfinance",
        },
        "fundamental_data": {
            "label": "Fundamental Data (financial statements)",
            "options": {
                "yfinance": "Yahoo Finance (default, no API key needed)",
                "alpha_vantage": "Alpha Vantage (free API key required)",
                "akshare": "AKShare (China markets, free)",
            },
            "default": "yfinance",
        },
        "news_data": {
            "label": "News & Insider Data",
            "options": {
                "yfinance": "Yahoo Finance (default, global, free)",
                "eastmoney": "East Money (China A-shares, free)",
                "sina_finance": "Sina Finance (China A-shares, free)",
                "alpha_vantage": "Alpha Vantage (free API key required)",
            },
            "default": "yfinance",
        },
        "social_sentiment": {
            "label": "Social Sentiment (StockTwits / Reddit / Chinese)",
            "options": {
                "all": "Both StockTwits + Reddit (default, global markets)",
                "stocktwits": "StockTwits only",
                "reddit": "Reddit only",
                "chinese": "Chinese A-share (Baidu vote + East Money 千股千评, via AKShare)",
                "baidu_vote": "Baidu stock vote only (看涨/看跌 ratio)",
                "em_comment": "East Money 千股千评 only (综合评分)",
            },
            "default": "all",
        },
    }

    selections: Dict[str, str] = {}
    for cat_key, cat_info in _CATEGORIES.items():
        choices = []
        for vendor_key, vendor_label in cat_info["options"].items():
            display = vendor_label
            if vendor_key == cat_info["default"]:
                display = f"{vendor_label}  (Default)"
            choices.append(questionary.Choice(display, value=vendor_key))

        chosen = questionary.select(
            f"Select {cat_info['label']}:",
            choices=choices,
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
            style=questionary.Style([
                ("selected", "fg:cyan noinherit"),
                ("highlighted", "fg:cyan noinherit"),
                ("pointer", "fg:cyan noinherit"),
            ]),
        ).ask()

        if chosen is None:
            continue

        if chosen != cat_info["default"]:
            selections[cat_key] = chosen

    return selections
