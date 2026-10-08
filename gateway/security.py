"""Password hashing and API-key/session authentication."""
from typing import Optional

import aiosqlite
from fastapi import HTTPException, Header, Request
from passlib.context import CryptContext

from gateway.config import system_db_path


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)


async def verify_api_key(request: Request, x_api_key: Optional[str] = Header(None), key: Optional[str] = None) -> str:
    # Check Header first, then Query Param
    # This endpoint uses "key" for the channel invite, not authentication.
    api_key = x_api_key or (None if request.url.path == "/api/newsletter/info-by-invite" else key)

    if not api_key:
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=401, detail="Silakan masuk atau sertakan API key.")
        from urllib.parse import urlsplit
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and urlsplit(origin).netloc != request.headers.get("host")):
            raise HTTPException(403, "Origin tidak diizinkan")
        async with aiosqlite.connect(system_db_path) as db:
            async with db.execute("SELECT username FROM users WHERE username=?", (user,)) as cursor:
                row = await cursor.fetchone()
        if row:
            return row[0]
        request.session.clear()
        raise HTTPException(401, "Sesi login sudah tidak berlaku.")

    async with aiosqlite.connect(system_db_path) as db:
        async with db.execute("SELECT username FROM users WHERE api_key=?", (api_key,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(status_code=403, detail="Invalid API Key")
            return row[0] # Returns username
