"""Compose the FastAPI application from independent API and service modules."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from gateway.config import prepare_runtime
from gateway.lifecycle import lifespan
from gateway.middleware import restrict_internal_routes
from gateway.routes import (
    airich,
    blast,
    customer_service,
    devices,
    groups,
    interactive,
    messages,
    newsletters,
    status,
    uploads,
    utilities,
)
from gateway.routes.dashboard import register_dashboard


def create_app() -> FastAPI:
    """Register middleware, API routers, dashboard endpoints, and static assets."""
    session_secret = prepare_runtime()
    application = FastAPI(
        title="WhatsApp Multi-Session Gateway",
        description="A FastAPI gateway for WhatsApp using neonize supporting multiple sessions & API Keys",
        version="1.5.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.middleware("http")(restrict_internal_routes)
    application.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        same_site="lax",
        https_only=os.getenv("GATEWAY_SECURE_COOKIE", "false").lower() == "true",
    )
    application.mount("/static", StaticFiles(directory="static"), name="static")
    for module in (
        uploads, blast, customer_service, devices, groups, messages, newsletters,
        interactive, airich, status, utilities,
    ):
        application.include_router(module.router)
    register_dashboard(application)
    return application


app = create_app()
