"""Tests for the API-key gate.

The service had no authentication of any kind across 93 endpoints, including
four static mounts of privileged material. See
docs/REDUCED_CORE_MANIFEST.md section 6.4.

Each test builds a tiny app with only the middleware and a couple of probe
routes -- this keeps the suite fast (no torch, no composition root) and tests the
gate in isolation.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.presentation.middleware import auth

KEY = "test-key-abc123"


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(auth.APIKeyMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/transcripts")
    async def protected():
        return {"transcripts": ["secret"]}

    @app.get("/transcripts/secret.json")
    async def protected_mount():
        return {"evidence": True}

    @app.get("/pinocchio")
    async def shell():
        return {"ui": True}

    @app.get("/aligner")
    async def aligner_shell():
        return {"ui": True}

    return app


@pytest.fixture()
def no_key(monkeypatch):
    monkeypatch.delenv(auth.ENV_VAR, raising=False)
    with TestClient(_app()) as c:
        yield c


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setenv(auth.ENV_VAR, KEY)
    with TestClient(_app()) as c:
        yield c


def test_public_path_classification() -> None:
    assert auth.is_public_path("/health")
    assert auth.is_public_path("/static/js/llm-providers.js")
    assert auth.is_public_path("/pinocchio")
    assert auth.is_public_path("/aligner")
    assert auth.is_public_path("/")
    # These carry evidence and must NOT be public.
    assert not auth.is_public_path("/api/transcripts")
    assert not auth.is_public_path("/transcripts/x.json")
    assert not auth.is_public_path("/audio/x.wav")
    assert not auth.is_public_path("/v1/llm/providers")


def test_disabled_when_no_key_configured(no_key) -> None:
    """Without a key the gate is open (safe only because of the loopback bind)."""
    assert no_key.get("/api/transcripts").status_code == 200
    assert no_key.get("/transcripts/secret.json").status_code == 200


def test_protected_route_requires_a_key(with_key) -> None:
    res = with_key.get("/api/transcripts")
    assert res.status_code == 401
    assert "unauthorized" in res.json()["detail"].lower()


def test_static_evidence_path_requires_a_key(with_key) -> None:
    """The mounts bypass Depends, so only middleware can protect them."""
    assert with_key.get("/transcripts/secret.json").status_code == 401


def test_health_and_shell_stay_public(with_key) -> None:
    assert with_key.get("/health").status_code == 200
    assert with_key.get("/pinocchio").status_code == 200


def test_public_shell_token_sets_auth_cookie(with_key) -> None:
    response = with_key.get("/aligner", params={"token": KEY})
    assert response.status_code == 200
    assert response.cookies.get(auth.COOKIE_NAME) == KEY


def test_x_api_key_header_authenticates(with_key) -> None:
    res = with_key.get("/api/transcripts", headers={"X-API-Key": KEY})
    assert res.status_code == 200


def test_bearer_token_authenticates(with_key) -> None:
    res = with_key.get(
        "/api/transcripts", headers={"Authorization": f"Bearer {KEY}"}
    )
    assert res.status_code == 200


def test_query_token_authenticates_and_sets_cookie(with_key) -> None:
    res = with_key.get(f"/api/transcripts?token={KEY}")
    assert res.status_code == 200
    assert auth.COOKIE_NAME in res.cookies


def test_cookie_authenticates_subsequent_requests(with_key) -> None:
    with_key.cookies.set(auth.COOKIE_NAME, KEY)
    assert with_key.get("/api/transcripts").status_code == 200


def test_wrong_key_is_rejected(with_key) -> None:
    assert with_key.get("/api/transcripts", headers={"X-API-Key": "nope"}).status_code == 401
    assert (
        with_key.get(
            "/api/transcripts", headers={"Authorization": "Bearer nope"}
        ).status_code
        == 401
    )
    assert with_key.get("/api/transcripts?token=nope").status_code == 401


def test_malformed_cookie_header_does_not_500(with_key) -> None:
    res = with_key.get("/api/transcripts", headers={"Cookie": "=;;;==="})
    assert res.status_code == 401


def test_malformed_bearer_prefix_is_rejected(with_key) -> None:
    assert (
        with_key.get("/api/transcripts", headers={"Authorization": "Bearer"}).status_code
        == 401
    )


def test_key_is_valid_uses_compare_digest() -> None:
    """Guard the constant-time property structurally."""
    import inspect

    src = inspect.getsource(auth.key_is_valid)
    assert "compare_digest" in src


def test_empty_expected_key_means_disabled() -> None:
    assert auth.key_is_valid([], "") is True


def test_rejection_logs_the_client(caplog) -> None:
    """A rejected request should be visible in the log, not silent."""
    import logging

    app = FastAPI()
    app.add_middleware(auth.APIKeyMiddleware)

    @app.get("/api/transcripts")
    async def protected():
        return {}

    import os

    os.environ[auth.ENV_VAR] = KEY
    try:
        with caplog.at_level(logging.WARNING), TestClient(app) as c:
            c.get("/api/transcripts")
        assert any("rejected" in r.message for r in caplog.records)
    finally:
        os.environ.pop(auth.ENV_VAR, None)
