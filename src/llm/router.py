"""LLM provider configuration and unified chat routing.

Endpoints
---------
GET    /v1/llm/providers                     list providers + model catalog + key status
POST   /v1/llm/providers/{provider}/key      store an API key (UI-managed)
DELETE /v1/llm/providers/{provider}/key      remove the stored API key
POST   /v1/llm/providers/{provider}/verify   validate a key against the provider
POST   /v1/llm/chat/completions              route a chat request to the right provider

API keys are resolved server-side from :mod:`src.llm.credentials`; the browser
never sends or receives them. Streaming is normalised to OpenAI-compatible SSE
regardless of the upstream provider's wire format.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import credentials as creds
from .providers import PROVIDERS, get_models, provider_kind, resolve_base_url

logger = logging.getLogger(__name__)

router = APIRouter()

_STREAM_TIMEOUT = httpx.Timeout(connect=15.0, read=None, write=60.0, pool=None)
_JSON_TIMEOUT = httpx.Timeout(120.0)

ANTHROPIC_VERSION = "2023-06-01"

# Only a known-safe subset of fields is forwarded upstream (see ChatRequest):
# response_format / tools / tool_choice are deliberately dropped so a provider
# that does not support them cannot break an otherwise valid request.


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ApiKeyPayload(BaseModel):
    # Optional so ``POST /verify`` can be called with no body at all (i.e. to
    # re-test a key that is already stored server-side).
    api_key: Optional[str] = Field(default=None, description="Provider API key")


class ChatMessage(BaseModel):
    role: str = "user"
    content: Any = ""


class ChatRequest(BaseModel):
    """Unified chat request accepted by ``/v1/llm/chat/completions``."""

    provider: str
    model: str
    messages: List[ChatMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    # Optional override, only ever supplied from the UI's advanced path.
    base_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_provider(provider: str) -> Dict[str, Any]:
    defn = PROVIDERS.get(provider)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
    return defn


async def _ollama_models() -> List[Dict[str, Any]]:
    """Model entries for the local Ollama provider (discovered at runtime)."""
    base = resolve_base_url("ollama") or ""
    root = base[:-3] if base.endswith("/v1") else base
    names: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{root}/api/tags")
        if resp.status_code < 400:
            for item in resp.json().get("models", []) or []:
                name = item.get("name") or item.get("model")
                if name:
                    names.append(str(name))
    except Exception as exc:
        logger.debug(f"Ollama model discovery failed: {exc}")

    return [
        {
            "id": name,
            "name": name,
            "provider": "ollama",
            "tier": "local",
            "context_window": None,
            "supports_vision": False,
            "supports_thinking": False,
            "best_for": "Local model",
        }
        for name in sorted(set(names))
    ]


def _resolve_models(provider: str, dynamic: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    if provider == "ollama" and dynamic:
        return dynamic
    return get_models(provider)


def _auth_headers(provider: str, api_key: Optional[str]) -> Dict[str, str]:
    defn = _require_provider(provider)
    if defn["kind"] == "anthropic":
        headers = {"Content-Type": "application/json", "anthropic-version": ANTHROPIC_VERSION}
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if provider == "openrouter":
        headers.setdefault("HTTP-Referer", "http://localhost:8049")
        headers.setdefault("X-Title", "Awareness-AI Transcription")
    return headers


def _chat_url(provider: str, override: Optional[str] = None) -> str:
    base = resolve_base_url(provider, override)
    if not base:
        raise HTTPException(status_code=400, detail=f"No base URL configured for '{provider}'")

    if provider_kind(provider) == "anthropic":
        return base if base.endswith("/messages") else f"{base}/messages"

    root = base[:-3] if base.endswith("/v1") else base
    return f"{root}/v1/chat/completions"


def _models_url(provider: str) -> Optional[str]:
    if provider_kind(provider) == "ollama":
        base = resolve_base_url(provider) or ""
        root = base[:-3] if base.endswith("/v1") else base
        return f"{root}/api/tags"

    base = resolve_base_url(provider)
    if not base:
        return None
    root = base[:-3] if base.endswith("/v1") else base
    return f"{root}/v1/models"


def _to_anthropic_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    system_chunks: List[str] = []
    messages: List[Dict[str, str]] = []

    for message in payload.get("messages", []):
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        content = str(content)

        if role == "system":
            if content.strip():
                system_chunks.append(content)
            continue
        messages.append({"role": "assistant" if role == "assistant" else "user", "content": content})

    if not messages:
        messages = [{"role": "user", "content": ""}]

    body: Dict[str, Any] = {
        "model": payload.get("model"),
        "messages": messages,
        "max_tokens": payload.get("max_tokens") or 2048,
    }
    if payload.get("temperature") is not None:
        body["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        body["top_p"] = payload["top_p"]
    if system_chunks:
        body["system"] = "\n\n".join(system_chunks)
    return body


def _anthropic_to_openai(upstream: Dict[str, Any], model: str) -> Dict[str, Any]:
    text = "".join(
        block.get("text", "")
        for block in upstream.get("content", [])
        if isinstance(block, dict)
    ).strip()
    usage = upstream.get("usage", {})
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    return {
        "id": upstream.get("id", "anthropic-response"),
        "object": "chat.completion",
        "created": 0,
        "model": upstream.get("model") or model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": upstream.get("stop_reason") or "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _openai_delta_chunk(text: str, model: str) -> str:
    return _sse({
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    })


def _error_payload(message: str) -> Dict[str, Any]:
    return {"error": {"message": message, "type": "provider_error"}}


async def _proxy_openai_stream(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> AsyncIterator[str]:
    """Stream an OpenAI-compatible provider response straight through."""
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "ignore")
                yield _sse(_error_payload(f"Upstream {resp.status_code}: {body[:500]}"))
                yield "data: [DONE]\n\n"
                return
            async for line in resp.aiter_lines():
                if line and line.strip():
                    yield f"{line}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_anthropic(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> AsyncIterator[str]:
    """Translate Anthropic SSE events into OpenAI-compatible chunks."""
    model = str(payload.get("model") or "")
    body = {**_to_anthropic_payload(payload), "stream": True}

    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                raw = (await resp.aread()).decode("utf-8", "ignore")
                yield _sse(_error_payload(f"Anthropic {resp.status_code}: {raw[:500]}"))
                yield "data: [DONE]\n\n"
                return

            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")
                if etype == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield _openai_delta_chunk(delta["text"], model)
                elif etype == "error":
                    detail = (event.get("error") or {}).get("message", "Anthropic stream error")
                    yield _sse(_error_payload(detail))
                elif etype == "message_stop":
                    break
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Provider / credential endpoints
# ---------------------------------------------------------------------------

@router.get("/v1/llm/providers", tags=["LLM"])
async def list_llm_providers():
    """Providers, their model catalog, and whether credentials are configured."""
    ollama_dynamic = await _ollama_models()
    summary = creds.credential_summary()

    providers: List[Dict[str, Any]] = []
    for provider_id, defn in PROVIDERS.items():
        status = summary.get(provider_id, {})
        providers.append({
            "id": provider_id,
            "label": defn["label"],
            "icon": defn.get("icon"),
            "kind": defn["kind"],
            "requires_key": bool(defn.get("requires_key")),
            "configured": status.get("configured", False),
            "key_source": status.get("source"),
            "key_masked": status.get("masked"),
            "models": _resolve_models(provider_id, ollama_dynamic),
        })

    return {"providers": providers}


@router.post("/v1/llm/providers/{provider}/key", tags=["LLM"])
async def set_llm_provider_key(provider: str, payload: ApiKeyPayload):
    _require_provider(provider)
    if not (payload.api_key or "").strip():
        raise HTTPException(status_code=400, detail="api_key must not be empty")
    creds.set_api_key(provider, payload.api_key.strip())
    return {
        "provider": provider,
        "configured": True,
        "key_masked": creds.masked_key(provider),
        "key_source": creds.get_source(provider),
    }


@router.delete("/v1/llm/providers/{provider}/key", tags=["LLM"])
async def clear_llm_provider_key(provider: str):
    _require_provider(provider)
    creds.clear_api_key(provider)
    return {
        "provider": provider,
        "configured": creds.is_configured(provider),
        "key_source": creds.get_source(provider),
    }


@router.post("/v1/llm/providers/{provider}/verify", tags=["LLM"])
async def verify_llm_provider_key(provider: str, payload: Optional[ApiKeyPayload] = None):
    """
    Validate a key by hitting the provider's model-list endpoint.

    Uses the submitted key when present, otherwise the stored/env key.
    """
    _require_provider(provider)
    api_key = (payload.api_key.strip() if payload and payload.api_key else None) or creds.get_api_key(provider)

    if provider_kind(provider) == "ollama":
        models = await _ollama_models()
        return {
            "provider": provider,
            "ok": bool(models),
            "model_count": len(models),
            "detail": None if models else "Ollama is not responding.",
        }

    if not api_key:
        raise HTTPException(status_code=400, detail=f"No API key available for '{provider}'")

    url = _models_url(provider)
    if not url:
        raise HTTPException(status_code=400, detail=f"No base URL configured for '{provider}'")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            resp = await client.get(url, headers=_auth_headers(provider, api_key))
        if resp.status_code >= 400:
            return JSONResponse(
                status_code=200,
                content={
                    "provider": provider,
                    "ok": False,
                    "status": resp.status_code,
                    "detail": resp.text[:300],
                },
            )
        data = resp.json()
        items = data.get("data") if isinstance(data, dict) else None
        count = len(items) if isinstance(items, list) else None
        return {"provider": provider, "ok": True, "model_count": count}
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={"provider": provider, "ok": False, "detail": str(exc)},
        )


# ---------------------------------------------------------------------------
# Unified chat
# ---------------------------------------------------------------------------

@router.post("/v1/llm/chat/completions", tags=["LLM"])
async def llm_chat_completions(req: ChatRequest):
    """
    Route a chat completion to the selected provider using server-side keys.

    Streaming requests return an OpenAI-compatible SSE stream regardless of
    the upstream provider's wire format.
    """
    provider = (req.provider or "").strip().lower()
    if not provider:
        raise HTTPException(status_code=400, detail="'provider' is required")
    defn = _require_provider(provider)

    api_key = creds.get_api_key(provider)
    if defn.get("requires_key") and not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key configured for '{defn['label']}'. Add one in the API Keys panel.",
        )

    payload: Dict[str, Any] = {
        "model": req.model,
        "messages": [m.model_dump() for m in req.messages],
        "temperature": req.temperature,
        "stream": bool(req.stream),
    }
    if req.top_p is not None:
        payload["top_p"] = req.top_p
    if req.max_tokens:
        payload["max_tokens"] = req.max_tokens

    url = _chat_url(provider, req.base_url)
    headers = _auth_headers(provider, api_key)
    kind = defn["kind"]

    if req.stream:
        generator = (
            _stream_anthropic(url, headers, payload)
            if kind == "anthropic"
            else _proxy_openai_stream(url, headers, payload)
        )
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    body = _to_anthropic_payload(payload) if kind == "anthropic" else payload
    try:
        async with httpx.AsyncClient(timeout=_JSON_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"{defn['label']} unreachable: {exc}")

    if resp.status_code >= 400:
        detail = f"{defn['label']} API error: {resp.text[:500]}"
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": detail}, "detail": detail},
        )

    data = resp.json()
    if kind == "anthropic":
        data = _anthropic_to_openai(data, str(req.model))
    return data
