"""HTTP routes of the evidence-api service (thin layer over ``core.py``)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["evidence-api"])
