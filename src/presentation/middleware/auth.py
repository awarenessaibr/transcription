"""API-key authentication for the transcription service.

The service exposes 93 endpoints with no authentication at all, including four
unauthenticated static mounts of privileged material (``/transcripts``,
``/audio``, ``/originals``, ``/speakers``) and destructive operations such as
``DELETE /api/projects/{id}``. This module adds a single, uniform gate
(docs/REDUCED_CORE_MANIFEST.md section 6.4).

Behaviour
---------
* ``TRANSCRIPTION_API_KEY`` unset  -> the gate is open and a warning is logged
  once at startup. This keeps local development and the existing test suite
  working, and is only safe because the app now binds to loopback by default.
* ``TRANSCRIPTION_API_KEY`` set    -> every request must present the key, except
  a small allowlist (§ ``PUBLIC_PATHS``) covering the health probe, static
  assets and the HTML shells (which contain no evidence).

Key presentation
----------------
Any of: ``X-API-Key: <key>``, ``Authorization: Bearer <key>``, ``?token=<key>``,
or the ``transcription_api_key`` cookie. A successful ``?token=`` presentation
sets the cookie, so a browser flow is: open ``/pinocchio?token=XYZ`` once and
subsequent XHRs carry the cookie.

Tokens are compared with :func:`secrets.compare_digest` to avoid leaking the key
through response timing.
"""
from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Iterable
from http.cookies import SimpleCookie

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

ENV_VAR = "TRANSCRIPTION_API_KEY"
COOKIE_NAME = "transcription_api_key"

#: Exact paths that never require a key: the liveness probe and the HTML shells.
#: The shells carry no evidence -- they are static templates; every data call
#: they make goes to a protected path.
PUBLIC_PATHS: frozenset[str] = frozenset({
    "/health",
    "/",
    "/pinocchio",
    "/pinocchio-en",
    "/revision",
    "/revision-en",
    "/aligner",
    "/speakers-registry",
    "/docs",
    "/openapi.json",
})

#: Prefixes that never require a key (static assets only).
PUBLIC_PREFIXES: tuple[str, ...] = ("/static/",)


def configured_key() -> str:
    """The expected key, or '' when the gate is disabled."""
    return (os.getenv(ENV_VAR) or "").strip()


def is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def presented_keys(request: Request) -> list[str]:
    """Every key the request presents, in no particular order."""
    found: list[str] = []

    header_key = request.headers.get("x-api-key")
    if header_key:
        found.append(header_key.strip())

    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        found.append(auth[7:].strip())

    query_token = request.query_params.get("token")
    if query_token:
        found.append(query_token.strip())

    raw_cookie = request.headers.get("cookie")
    if raw_cookie:
        try:
            jar = SimpleCookie()
            jar.load(raw_cookie)
            morsel = jar.get(COOKIE_NAME)
            if morsel is not None and morsel.value:
                found.append(morsel.value.strip())
        except Exception:  # malformed Cookie header must not 500
            logger.debug("[auth] could not parse Cookie header")

    return found


def key_is_valid(presented: Iterable[str], expected: str) -> bool:
    """Constant-time membership test.

    ``secrets.compare_digest`` is used per candidate so the comparison does not
    leak the key through response timing.
    """
    if not expected:
        return True
    return any(secrets.compare_digest(candidate, expected) for candidate in presented)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated requests when ``TRANSCRIPTION_API_KEY`` is set."""

    async def dispatch(self, request: Request, call_next) -> Response:
        expected = configured_key()
        if not expected:
            return await call_next(request)

        if is_public_path(request.url.path):
            response = await call_next(request)
            if request.query_params.get("token") and key_is_valid(
                [request.query_params["token"].strip()], expected
            ):
                response.set_cookie(
                    COOKIE_NAME,
                    expected,
                    httponly=True,
                    samesite="lax",
                    secure=request.url.scheme == "https",
                )
            return response

        presented = presented_keys(request)
        if not key_is_valid(presented, expected):
            logger.warning(
                "[auth] rejected %s %s from %s",
                request.method,
                request.url.path,
                request.client.host if request.client else "?",
            )
            return JSONResponse(
                {"detail": "unauthorized: missing or invalid API key"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        response = await call_next(request)
        # Persist a key supplied via ?token= so browser XHRs authenticate too.
        if request.query_params.get("token"):
            response.set_cookie(
                COOKIE_NAME,
                expected,
                httponly=True,
                samesite="lax",
                secure=request.url.scheme == "https",
            )
        return response


def warn_if_disabled() -> None:
    """Log once, loudly, when the service is running without a key."""
    if configured_key():
        logger.info("[auth] API-key authentication enabled (%s is set)", ENV_VAR)
    else:
        logger.warning(
            "[auth] %s is not set: the API is UNAUTHENTICATED. Bind to "
            "127.0.0.1 (the default) or set the key before exposing this port.",
            ENV_VAR,
        )
