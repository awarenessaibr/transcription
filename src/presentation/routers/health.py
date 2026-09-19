"""Health check router."""
from __future__ import annotations

import torch
from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "transcription",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "transcription",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
