"""Blast API routes."""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from gateway.messages.models import BlastRequest
from gateway.services.blast import run_blast


router = APIRouter()


@router.post("/api/blast", include_in_schema=False)
async def api_blast(data: BlastRequest, request: Request):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")

    if not data.devices:
        raise HTTPException(status_code=400, detail="No devices selected")

    asyncio.create_task(run_blast(user, data.phone_data, data.message, data.delay_min, data.delay_max, data.devices))

    return {"success": True, "message": "Blast campaign started in background"}
