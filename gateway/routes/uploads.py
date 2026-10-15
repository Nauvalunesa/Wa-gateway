"""Uploads API routes."""
import os
import secrets
import shutil

from fastapi import APIRouter, File, HTTPException, Request, UploadFile


router = APIRouter()


@router.post("/api/upload", include_in_schema=False)
async def upload_file(request: Request, file: UploadFile = File(...)):
    user = request.session.get("user")
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")

    file_ext = os.path.splitext(file.filename)[1]
    file_name = f"{secrets.token_hex(8)}{file_ext}"
    file_path = os.path.join("static/uploads", file_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Return the full URL that can be accessed by the bot
    # We use request.base_url to get the current domain
    base_url = str(request.base_url).rstrip("/")
    return {"success": True, "url": f"{base_url}/static/uploads/{file_name}"}
