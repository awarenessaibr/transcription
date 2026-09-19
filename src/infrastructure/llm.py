"""Minimal JSON-in / JSON-out LLM helper for server-side features.

The browser talks to providers through ``POST /v1/llm/chat/completions``
(:mod:`src.llm.router`), which resolves API keys server-side. This module is the
in-process equivalent, for features that need structured JSON back from a model
without a browser round-trip — currently the law-registry payload review.

Contract::

    call_llm_json(system, user, *, provider=None, model=None) -> dict

The returned dict is the parsed JSON body of the model's reply, augmented with
``_model`` and ``_usage`` for telemetry. Provider and model resolution reuse the
same registry (:mod:`src.llm.providers`) and credential store
(:mod:`src.llm.credentials`) as the HTTP route, so a key entered in any UI works
here unchanged and the wire format (including the Anthropic translation) is the
same one the rest of the app already speaks.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from src.config import settings
from src.llm import credentials as creds
from src.llm.providers import PROVIDERS, get_models, provider_kind, resolve_base_url

# Reuse the router's pure wire-format translators so a server-side call and a
# browser call to the same provider cannot drift apart.
from src.llm.router import _anthropic_to_openai, _to_anthropic_payload

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
_REQUEST_TIMEOUT = httpx.Timeout(connect=15.0, read=180.0, write=60.0, pool=None)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(RuntimeError):
    """Raised when the provider call fails or the reply is not usable JSON."""


# Reasoning models can spend the *entire* completion budget on
# ``reasoning_content`` and then return an empty ``content`` with
# ``finish_reason="length"`` — measured against the configured endpoint: 4096 and
# 8192 ``max_tokens`` both yielded 0 characters of content and ~9k tokens of
# reasoning, so raising the budget does not help. ``reasoning_effort="none"``
# zeroes it there (completion_tokens 30 -> 12 on a probe) and is the
# OpenAI-standard spelling, so it is sent for the OpenAI-compatible providers and
# dropped again if a provider rejects the parameter outright.
_NO_REASONING: dict[str, Any] = {"reasoning_effort": "none"}


def _post_chat(url: str, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
    """POST one chat completion, translating transport failures into ``LLMError``."""
    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
            return client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise LLMError(f"request to {url} failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Provider / model resolution
# ---------------------------------------------------------------------------
def configured_providers() -> list[str]:
    """Provider ids that are usable right now (in registry order)."""
    return [provider_id for provider_id in PROVIDERS if creds.is_configured(provider_id)]


def serviceable_providers() -> list[str]:
    """Configured providers that also have a model to call.

    A local Ollama daemon counts as configured as soon as it answers, and it
    sorts first in the registry, so auto-detection landing on it with zero
    models pulled would fail every request with "No model chosen for provider
    'ollama'". Providers with an empty catalog are therefore not candidates for
    auto-detection (they remain selectable explicitly, where the missing model
    is reported as such).
    """
    return [provider_id for provider_id in configured_providers() if get_models(provider_id)]


def resolve_provider(explicit: str | None = None) -> str:
    """Pick a provider: the explicit one, the configured default, else the first usable."""
    candidate = (explicit or getattr(settings, "LAW_REVIEW_PROVIDER", "") or "").strip()
    if candidate:
        if candidate not in PROVIDERS:
            raise LLMError(f"Unknown LLM provider: {candidate!r}")
        if not creds.is_configured(candidate):
            raise LLMError(f"Provider {candidate!r} has no API key configured")
        return candidate

    # Falling back to the merely-configured list keeps the failure pointing at the
    # missing model rather than at a supposedly missing API key.
    available = serviceable_providers() or configured_providers()
    if not available:
        raise LLMError("No LLM provider is configured — add an API key under LLM providers")
    return available[0]


def resolve_model(provider: str, explicit: str | None = None) -> str:
    """Pick a model: the explicit one, the configured default, else the first in the catalog."""
    candidate = (explicit or "").strip()
    if candidate:
        return candidate

    default_provider = (getattr(settings, "LAW_REVIEW_PROVIDER", "") or "").strip()
    default_model = (getattr(settings, "LAW_REVIEW_MODEL", "") or "").strip()
    if default_model and (not default_provider or default_provider == provider):
        return default_model

    models = get_models(provider)
    if models:
        return str(models[0]["id"])
    raise LLMError(f"No model chosen for provider {provider!r} — pass one explicitly")


# ---------------------------------------------------------------------------
# Request plumbing
# ---------------------------------------------------------------------------
def _chat_url(provider: str) -> str:
    base = (resolve_base_url(provider) or "").rstrip("/")
    if not base:
        raise LLMError(f"No base URL configured for provider {provider!r}")
    if provider_kind(provider) == "anthropic":
        return base if base.endswith("/messages") else f"{base}/messages"
    root = base[:-3] if base.endswith("/v1") else base
    return f"{root}/v1/chat/completions"


def _headers(provider: str, api_key: str | None) -> dict[str, str]:
    if provider_kind(provider) == "anthropic":
        headers = {"Content-Type": "application/json", "anthropic-version": ANTHROPIC_VERSION}
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def parse_json_reply(raw: str) -> dict[str, Any]:
    """Parse a model reply into a JSON object, tolerating fences and stray prose."""
    text = (raw or "").strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    if not text:
        raise LLMError("the model returned an empty reply")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some providers wrap the object in a sentence; slice the outermost one.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError(f"the model did not return JSON: {text[:200]!r}") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"the model did not return JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise LLMError("the model returned JSON that is not an object")
    return data


def _message_text(upstream: dict[str, Any]) -> str:
    choices = upstream.get("choices") or []
    if not choices:
        raise LLMError("the provider returned no completion")
    choice = choices[0]
    content = (choice.get("message") or {}).get("content")
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    text = str(content or "")
    if text.strip():
        return text

    # An empty answer is almost always the reasoning budget, not a silent model:
    # say which, so the caller can act instead of guessing.
    reasoning = (choice.get("message") or {}).get("reasoning_content") or ""
    finish = choice.get("finish_reason")
    if reasoning:
        raise LLMError(
            f"the model spent the whole completion budget on reasoning "
            f"({len(str(reasoning))} chars of reasoning, finish_reason={finish!r}, no content)"
        )
    raise LLMError(f"the model returned an empty reply (finish_reason={finish!r})")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def call_llm_json(
    system: str,
    user: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Send one system+user exchange and return the model's reply parsed as JSON.

    Raises :class:`LLMError` for anything the caller can surface as a 502: an
    unknown/unconfigured provider, a transport failure, an HTTP error from the
    provider, or a reply that is not a JSON object.
    """
    resolved_provider = resolve_provider(provider)
    resolved_model = resolve_model(resolved_provider, model)
    kind = provider_kind(resolved_provider)

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # ``response_format`` is deliberately not sent: it is unsupported by several
    # providers in the registry and the prompt already demands bare JSON.
    body = _to_anthropic_payload(payload) if kind == "anthropic" else {**payload, **_NO_REASONING}

    url = _chat_url(resolved_provider)
    headers = _headers(resolved_provider, creds.get_api_key(resolved_provider))
    response = _post_chat(url, headers, body)

    # Not every OpenAI-compatible gateway accepts ``reasoning_effort``. If that is
    # what it objected to, the retry is the same request minus the knob.
    if (
        response.status_code == 400
        and "reasoning_effort" in body
        and "reasoning_effort" in response.text
    ):
        logger.info("[llm] %s rejected reasoning_effort — retrying without it", resolved_provider)
        body.pop("reasoning_effort")
        response = _post_chat(url, headers, body)

    if response.status_code >= 400:
        raise LLMError(f"{resolved_provider} returned HTTP {response.status_code}: {response.text[:300]}")

    try:
        upstream = response.json()
    except ValueError as exc:
        raise LLMError(f"{resolved_provider} returned a non-JSON response") from exc

    if kind == "anthropic":
        upstream = _anthropic_to_openai(upstream, resolved_model)

    data = parse_json_reply(_message_text(upstream))
    data["_model"] = upstream.get("model") or resolved_model
    usage = upstream.get("usage")
    data["_usage"] = usage if isinstance(usage, dict) else None
    return data


__all__ = [
    "LLMError",
    "call_llm_json",
    "configured_providers",
    "parse_json_reply",
    "resolve_model",
    "resolve_provider",
    "serviceable_providers",
]
