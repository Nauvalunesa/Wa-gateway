"""Cookie-authenticated control for the account's built-in ping reply."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictBool

from gateway.security import dashboard_user
from gateway.services.ping import ping_enabled, save_ping_enabled

router = APIRouter()


class PingSettings(BaseModel):
    enabled: StrictBool


@router.get("/api/web/ping-settings")
async def get_ping_settings(username: str = Depends(dashboard_user)):
    return {"enabled": ping_enabled(username)}


@router.put("/api/web/ping-settings")
async def put_ping_settings(data: PingSettings, username: str = Depends(dashboard_user)):
    save_ping_enabled(username, data.enabled)
    return {"success": True, "enabled": data.enabled}
