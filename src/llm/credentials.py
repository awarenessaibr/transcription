"""Server-side store for LLM provider API keys.

Keys entered in the UI are persisted to ``llm_credentials.json`` next to this
file (git-ignored, mode 0600). Environment variables act as a fallback so a
fresh checkout keeps working without entering anything in the UI.

Secrets are never returned to the client — callers use :func:`masked_key` and
:func:`is_configured` instead.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .providers import PROVIDERS

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent
CREDENTIALS_PATH = CONFIG_DIR / "llm_credentials.json"

_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None


def _empty_store() -> Dict[str, Any]:
    return {"version": 1, "providers": {}}


def _read() -> Dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    if not CREDENTIALS_PATH.exists():
        _cache = _empty_store()
        return _cache
    try:
        with CREDENTIALS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not isinstance(data.get("providers"), dict):
            data = _empty_store()
        _cache = data
    except Exception as exc:  # pragma: no cover
        logger.warning(f"Could not read {CREDENTIALS_PATH.name}: {exc}")
        _cache = _empty_store()
    return _cache


def _write(store: Dict[str, Any]) -> None:
    global _cache
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CREDENTIALS_PATH.with_name(CREDENTIALS_PATH.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)
        os.chmod(tmp, 0o600)
        tmp.replace(CREDENTIALS_PATH)
        _cache = store
    except Exception as exc:
        logger.error(f"Could not persist {CREDENTIALS_PATH.name}: {exc}")
        raise


def _env_key(provider: str) -> Optional[str]:
    defn = PROVIDERS.get(provider)
    env_var = defn.get("env_var") if defn else None
    if not env_var:
        return None
    value = os.environ.get(env_var)
    return value.strip() if value else None


def get_api_key(provider: str) -> Optional[str]:
    """Return the effective key for ``provider`` (stored key wins over env)."""
    with _lock:
        entry = _read()["providers"].get(provider) or {}
        stored = entry.get("api_key")
        if stored:
            return str(stored).strip()
    return _env_key(provider)


def is_configured(provider: str) -> bool:
    """
    Whether the provider is usable.

    Ollama needs no key. Everything else needs a stored key or an env var.
    """
    defn = PROVIDERS.get(provider)
    if not defn:
        return False
    if not defn.get("requires_key"):
        return True
    return bool(get_api_key(provider))


def get_source(provider: str) -> Optional[str]:
    """Where the effective key came from: ``"ui"``, ``"env"`` or ``None``."""
    with _lock:
        entry = _read()["providers"].get(provider) or {}
        if entry.get("api_key"):
            return "ui"
    if _env_key(provider):
        return "env"
    return None


def masked_key(provider: str) -> Optional[str]:
    """A non-reversible hint of the stored key, e.g. ``sk-1…a2b3``."""
    key = get_api_key(provider)
    if not key:
        return None
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 6}{key[-4:]}"


def set_api_key(provider: str, api_key: str) -> None:
    """Persist ``api_key`` for ``provider``."""
    if provider not in PROVIDERS:
        raise KeyError(provider)
    value = (api_key or "").strip()
    if not value:
        raise ValueError("api_key must not be empty")

    with _lock:
        store = json.loads(json.dumps(_read()))  # deep copy
        store.setdefault("providers", {})[provider] = {
            "api_key": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write(store)


def clear_api_key(provider: str) -> None:
    """
    Remove a UI-stored key.

    An environment-variable key (if any) becomes effective again.
    """
    if provider not in PROVIDERS:
        raise KeyError(provider)
    with _lock:
        store = json.loads(json.dumps(_read()))
        store.setdefault("providers", {}).pop(provider, None)
        _write(store)


def credential_summary() -> Dict[str, Dict[str, Any]]:
    """Per-provider non-secret status used by the API response."""
    return {
        provider: {
            "configured": is_configured(provider),
            "requires_key": bool(defn.get("requires_key")),
            "source": get_source(provider),
            "masked": masked_key(provider),
        }
        for provider, defn in PROVIDERS.items()
    }
