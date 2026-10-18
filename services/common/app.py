"""FastAPI application factory shared by every service.

Each service's ``main.py`` calls :func:`create_app` with its name and router, so all
services expose the same ``GET /health`` endpoint, log in the same format and report
their version the same way. Keeping this in one place means a new service only has
to write its domain logic (``core.py``) and its routes (``api.py``).
"""

from __future__ import annotations

import logging
import os
import platform
import sys

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.common.schemas import SCHEMA_VERSION

# Version reported by /health; set at build time or in the environment.
SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "0.1.0")

# Log format without any payload: services only log ids, counts and timings, never
# health data (CLAUDE.md section 1.7).
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging() -> None:
    """Configure root logging once, at the level given by ``LOG_LEVEL`` (INFO)."""
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stdout, force=True)


def create_app(service_name: str, router: APIRouter | None = None, *routers: APIRouter) -> FastAPI:
    """Build a FastAPI app with the shared ``/health`` route and the service router.

    Args:
        service_name: Name used in docker compose (``kebab-case``), reported by /health.
        router: Routes of the service, usually ``api.router``.
        *routers: Further routers (e.g. sessions in evidence-api).

    Returns:
        The configured application.
    """
    configure_logging()
    app = FastAPI(
        title=f"Mental health Holter · {service_name}",
        version=SERVICE_VERSION,
        docs_url="/docs",
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness probe used by docker compose and the smoke test."""
        return {
            "status": "ok",
            "service": service_name,
            "version": SERVICE_VERSION,
            "schema_version": SCHEMA_VERSION,
            # Shows the jury that the service runs on LinuxONE (s390x, big-endian).
            "machine": platform.machine(),
            "byteorder": sys.byteorder,
        }

    # The frontend may be served from another origin (e.g. Vercel) and call this API
    # directly: allow only the origins listed in ALLOWED_ORIGINS (issue #14).
    origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )
    for extra in routers:
        app.include_router(extra)
    if router is not None:
        app.include_router(router)
    logging.getLogger(__name__).info("service=%s version=%s ready", service_name, SERVICE_VERSION)
    return app
