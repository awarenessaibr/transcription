"""LLM provider registry and model catalog.

Single source of truth for which providers the UI can talk to, how to
authenticate against each one, and which models each one exposes.

The catalog is the merge of:
  1. ``DEFAULT_MODELS`` below (curated, always available)
  2. ``models-overrides.json`` next to this file (``added`` / ``overrides`` / ``removed``)
  3. Ollama models discovered at runtime (dynamic, local provider only)

Nothing here holds secrets — see :mod:`src.llm.credentials` for that.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent
MODELS_OVERRIDES_PATH = CONFIG_DIR / "models-overrides.json"

DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434"

# ``kind`` drives how a request is built:
#   "openai"    -> OpenAI-compatible POST {base_url}/chat/completions
#   "anthropic" -> POST {base_url}/messages (Anthropic message format)
#   "ollama"    -> local Ollama's OpenAI-compatible endpoint
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "ollama": {
        "label": "Ollama",
        "icon": "fa-hard-drive",
        "kind": "ollama",
        "base_url": None,  # resolved from env at request time
        "env_var": None,
        "requires_key": False,
    },
    "deepseek": {
        "label": "DeepSeek",
        "icon": "fa-brain",
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "env_var": "DEEPSEEK_API_KEY",
        "requires_key": True,
    },
    "cerebras": {
        "label": "Cerebras",
        "icon": "fa-microchip",
        "kind": "openai",
        "base_url": "https://api.cerebras.ai/v1",
        "env_var": "CEREBRAS_API_KEY",
        "requires_key": True,
    },
    "xai": {
        "label": "Grok (xAI)",
        "icon": "fa-bolt",
        "kind": "openai",
        "base_url": "https://api.x.ai/v1",
        "env_var": "XAI_API_KEY",
        "requires_key": True,
    },
    "anthropic": {
        "label": "Anthropic",
        "icon": "fa-feather-pointed",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "env_var": "ANTHROPIC_API_KEY",
        "requires_key": True,
    },
    "openrouter": {
        "label": "OpenRouter",
        "icon": "fa-network-wired",
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "env_var": "OPENROUTER_API_KEY",
        "requires_key": True,
    },
    "fireworks": {
        "label": "Fireworks",
        "icon": "fa-fire",
        "kind": "openai",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "env_var": "FIREWORKS_API_KEY",
        "requires_key": True,
    },
}


def _model(
    model_id: str,
    name: str,
    *,
    tier: Optional[str] = None,
    context_window: Optional[int] = None,
    supports_vision: bool = False,
    supports_thinking: bool = False,
    best_for: str = "",
) -> Dict[str, Any]:
    return {
        "id": model_id,
        "name": name,
        "tier": tier,
        "context_window": context_window,
        "supports_vision": supports_vision,
        "supports_thinking": supports_thinking,
        "best_for": best_for,
    }


# Curated defaults. Kept intentionally small — the overrides file is the
# primary way to extend this list without touching code.
DEFAULT_MODELS: Dict[str, List[Dict[str, Any]]] = {
    "ollama": [],
    "deepseek": [
        _model("deepseek-chat", "DeepSeek Chat", tier="paid", context_window=131072,
               best_for="General chat, RAG answers, structured JSON"),
        _model("deepseek-reasoner", "DeepSeek Reasoner", tier="paid", context_window=131072,
               supports_thinking=True, best_for="Multi-step reasoning and analysis"),
    ],
    "cerebras": [
        _model("llama3.1-8b", "Llama 3.1 8B", tier="free", context_window=131072,
               best_for="Fast drafts and cheap bulk work"),
        _model("llama-3.3-70b", "Llama 3.3 70B", tier="free", context_window=131072,
               best_for="Strong open-model general reasoning"),
        _model("qwen-3-32b", "Qwen 3 32B", tier="free", context_window=131072,
               supports_thinking=True, best_for="Reasoning and multilingual"),
        _model("gpt-oss-120b", "GPT-OSS 120B", tier="free", context_window=131072,
               supports_thinking=True, best_for="Open-weight flagship quality"),
    ],
    "xai": [
        _model("grok-4", "Grok 4", tier="paid", context_window=256000,
               supports_thinking=True, best_for="Frontier reasoning"),
        _model("grok-4-fast-reasoning", "Grok 4 Fast (Reasoning)", tier="paid",
               context_window=2000000, supports_thinking=True,
               best_for="Long-context reasoning at speed"),
        _model("grok-4-fast-non-reasoning", "Grok 4 Fast", tier="paid",
               context_window=2000000, best_for="Long-context chat without thinking overhead"),
        _model("grok-3-mini", "Grok 3 Mini", tier="paid", context_window=131072,
               supports_thinking=True, best_for="Cheap reasoning"),
    ],
    "anthropic": [
        _model("claude-opus-4-1", "Claude Opus 4.1", tier="paid", context_window=200000,
               supports_vision=True, supports_thinking=True, best_for="Highest-quality analysis"),
        _model("claude-sonnet-4-5", "Claude Sonnet 4.5", tier="paid", context_window=200000,
               supports_vision=True, supports_thinking=True, best_for="Balanced quality/throughput"),
        _model("claude-haiku-4-5", "Claude Haiku 4.5", tier="paid", context_window=200000,
               supports_vision=True, best_for="Fast, cheap classification and extraction"),
    ],
    "openrouter": [
        _model("openrouter/free", "Auto-Route (Free)", tier="free", context_window=131072,
               best_for="OpenRouter auto-routing to any currently-free model"),
    ],
    "fireworks": [],
}


def _load_overrides() -> Dict[str, Any]:
    """Best-effort read of ``models-overrides.json``."""
    if not MODELS_OVERRIDES_PATH.exists():
        return {}
    try:
        with MODELS_OVERRIDES_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # pragma: no cover - malformed config shouldn't 500
        logger.warning(f"Could not read {MODELS_OVERRIDES_PATH.name}: {exc}")
        return {}


def _normalize_raw(raw: Dict[str, Any], provider: str) -> Dict[str, Any]:
    """Normalize an override entry into the catalog model shape."""
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or raw.get("id"),
        "provider": raw.get("provider") or provider,
        "base_url": raw.get("base_url"),
        "tier": raw.get("tier"),
        "context_window": raw.get("context_window"),
        "input_cost_per_1m": raw.get("input_cost_per_1m"),
        "output_cost_per_1m": raw.get("output_cost_per_1m"),
        "supports_vision": bool(raw.get("supports_vision")),
        "supports_thinking": bool(raw.get("supports_thinking")),
        "best_for": raw.get("best_for") or "",
    }


def get_models(provider: str) -> List[Dict[str, Any]]:
    """
    Return the merged model catalog for ``provider``.

    Applies, in order: defaults -> ``added`` -> ``overrides`` -> ``removed``.
    """
    overrides = _load_overrides()

    models: List[Dict[str, Any]] = [
        {**m, "provider": provider} for m in DEFAULT_MODELS.get(provider, [])
    ]

    for raw in overrides.get("added") or []:
        if not isinstance(raw, dict):
            continue
        if (raw.get("provider") or provider) != provider:
            continue
        normalized = _normalize_raw(raw, provider)
        if not normalized.get("id"):
            continue
        models.append(normalized)

    model_overrides = overrides.get("overrides") or {}
    resolved: List[Dict[str, Any]] = []
    for model in models:
        patch = model_overrides.get(model["id"])
        if isinstance(patch, dict):
            if patch.get("hidden"):
                continue
            if patch.get("name"):
                model = {**model, "name": patch["name"]}
        resolved.append(model)

    removed = {r for r in (overrides.get("removed") or []) if isinstance(r, str)}
    resolved = [m for m in resolved if m["id"] not in removed]

    seen = set()
    unique: List[Dict[str, Any]] = []
    for model in resolved:
        key = (model["id"], model.get("tier"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(model)
    return unique


def get_provider(provider: str) -> Optional[Dict[str, Any]]:
    """Return a provider definition (copy) or ``None`` if unknown."""
    defn = PROVIDERS.get(provider)
    return dict(defn) if defn else None


def provider_kind(provider: str) -> Optional[str]:
    defn = PROVIDERS.get(provider)
    return defn.get("kind") if defn else None


def _normalize_ollama_base(raw: str) -> str:
    """
    Turn an ``OLLAMA_HOST``-style value into a connectable HTTP base URL.

    ``OLLAMA_HOST`` is a *bind* address (often ``0.0.0.0:11434``), which is not
    a valid destination for an outbound client request — rewrite it to
    ``127.0.0.1`` and add the scheme when it is missing.
    """
    value = (raw or "").strip().rstrip("/")
    if not value:
        return DEFAULT_OLLAMA_BASE
    if "://" not in value:
        value = f"http://{value}"
    if value.startswith("http://0.0.0.0"):
        value = value.replace("http://0.0.0.0", "http://127.0.0.1", 1)
    elif value.startswith("https://0.0.0.0"):
        value = value.replace("https://0.0.0.0", "https://127.0.0.1", 1)
    return value


def resolve_base_url(provider: str, override: Optional[str] = None) -> Optional[str]:
    """
    Resolve the request base URL for a provider.

    Priority: explicit override -> env var (``<PROVIDER>_BASE_URL``) -> registry.
    Ollama resolves from ``OLLAMA_BASE_URL`` / ``OLLAMA_HOST``.
    """
    if override:
        return override.rstrip("/")

    defn = PROVIDERS.get(provider)
    if not defn:
        return None

    if provider == "ollama":
        env_url = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")
        return _normalize_ollama_base(str(env_url or DEFAULT_OLLAMA_BASE))

    env_url = os.environ.get(f"{provider.upper()}_BASE_URL")
    if env_url:
        return env_url.rstrip("/")

    base = defn.get("base_url")
    return base.rstrip("/") if base else None


def public_providers() -> List[Dict[str, Any]]:
    """
    Provider registry enriched with the model catalog, safe for the client.

    Excludes auth env var names and any secret material.
    """
    out: List[Dict[str, Any]] = []
    for provider_id, defn in PROVIDERS.items():
        out.append({
            "id": provider_id,
            "label": defn["label"],
            "icon": defn.get("icon"),
            "kind": defn["kind"],
            "requires_key": bool(defn.get("requires_key")),
            "models": get_models(provider_id),
        })
    return out
