"""Session-authenticated dashboard API and the compiled React application."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import secrets
import sqlite3
from typing import Literal

import aiosqlite
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gateway.config import PROJECT_ROOT, system_db_path
from gateway.database import init_user_db
from gateway.messages.models import AIRichBlock
from gateway.routes.groups import api_get_groups
from gateway.security import hash_password, verify_password
from gateway.services.auto_reply import get_airich_auto_rules, save_airich_auto_rules
from gateway.state import bot_numbers, bot_status, clients, pairing_sessions


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-zA-Z0-9_]+$')
    password: str = Field(min_length=8, max_length=72)


class AIRichAutoRule(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    keyword: str = Field(min_length=1, max_length=128)
    match: Literal['contains', 'exact'] = 'contains'
    scope: Literal['all', 'private', 'group'] = 'all'
    cooldown_seconds: int = Field(default=30, ge=0, le=86400)
    blocks: list[dict] = Field(min_length=1, max_length=20)


class AIRichAutoRulesPayload(BaseModel):
    rules: list[AIRichAutoRule] = Field(default_factory=list, max_length=100)


def register_dashboard(app):
    async def current_user(request: Request):
        username = request.session.get('user')
        if username:
            async with aiosqlite.connect(system_db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute('SELECT username, api_key FROM users WHERE username=?', (username,)) as cursor:
                    row = await cursor.fetchone()
            if row:
                return dict(row)
        request.session.clear()
        raise HTTPException(401, 'Silakan masuk ke akun Anda.')

    @app.middleware('http')
    async def check_dashboard_origin(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path.startswith(('/api/web/', '/api/pair', '/api/logout_device', '/api/upload', '/api/blast')):
            origin = request.headers.get('origin')
            if origin:
                from urllib.parse import urlsplit
                source = urlsplit(origin).netloc
                if source != request.headers.get('host'):
                    return HTMLResponse('Origin tidak diizinkan', status_code=403)
        return await call_next(request)

    @app.post('/api/web/register')
    async def register(data: Credentials, request: Request):
        if len(data.password.encode('utf-8')) > 72:
            raise HTTPException(422, 'Password maksimal 72 byte.')
        hashed = await asyncio.to_thread(hash_password, data.password)
        key = secrets.token_hex(24)
        try:
            async with aiosqlite.connect(system_db_path) as db:
                await db.execute('INSERT INTO users (username,password,api_key) VALUES (?,?,?)', (data.username, hashed, key))
                await db.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, 'Username sudah digunakan.') from exc
        # User folders and message history are initialized by the first
        # dashboard overview request. Keep registration limited to the
        # credential write so a slow history database cannot hold the form open.
        request.session.clear()
        request.session['user'] = data.username
        return {'username': data.username, 'api_key': key}

    @app.post('/api/web/login')
    async def login(data: Credentials, request: Request):
        async with aiosqlite.connect(system_db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT username,password,api_key FROM users WHERE username=?', (data.username,)) as cursor:
                row = await cursor.fetchone()
        valid = False
        if row:
            try:
                valid = await asyncio.to_thread(verify_password, data.password, row['password'])
            except (ValueError, TypeError):
                pass
        if not valid:
            raise HTTPException(401, 'Username atau password salah.')
        await init_user_db(row['username'])
        request.session.clear()
        request.session['user'] = row['username']
        return {'username': row['username'], 'api_key': row['api_key']}

    @app.get('/api/web/me')
    async def me(user=Depends(current_user)):
        return user

    @app.post('/api/web/logout')
    async def logout(request: Request):
        request.session.clear()
        return {'success': True}

    @app.get('/logout', include_in_schema=False)
    async def logout_redirect(request: Request):
        request.session.clear()
        return RedirectResponse('/login', status_code=303)

    @app.post('/api/web/api-key')
    async def regenerate_key(user=Depends(current_user)):
        key = secrets.token_hex(24)
        async with aiosqlite.connect(system_db_path) as db:
            await db.execute('UPDATE users SET api_key=? WHERE username=?', (key, user['username']))
            await db.commit()
        return {'api_key': key}

    def devices_for(username):
        directory = Path('storage') / username / 'sessions'
        phones = {p.stem for p in directory.glob('*.sqlite3') if p.stem != 'session'}
        phones.update(sid.split(':', 1)[1] for sid in clients if sid.startswith(username + ':'))
        return [{'phone': ph, 'number': bot_numbers.get(f'{username}:{ph}', ph),
                 'online': bool(bot_status.get(f'{username}:{ph}')),
                 'pairing': f'{username}:{ph}' in pairing_sessions}
                for ph in sorted(phones)]

    @app.get('/api/web/devices')
    async def devices(user=Depends(current_user)):
        return {'devices': devices_for(user['username'])}

    @app.get('/api/web/groups')
    async def dashboard_groups(phone: str | None = Query(None), user=Depends(current_user)):
        """Return the signed-in user's joined groups to the web composer."""
        return await api_get_groups(phone=phone, username=user['username'])

    @app.get('/api/web/airich/auto-replies')
    async def get_airich_auto_replies(user=Depends(current_user)):
        return {'rules': get_airich_auto_rules(user['username'])}

    @app.put('/api/web/airich/auto-replies')
    async def put_airich_auto_replies(data: AIRichAutoRulesPayload, user=Depends(current_user)):
        rules = [rule.model_dump() for rule in data.rules]
        for rule in rules:
            try:
                for block in rule['blocks']:
                    AIRichBlock.model_validate(block)
            except Exception as exc:
                raise HTTPException(422, f"Aturan '{rule['keyword']}': {exc}") from exc
        save_airich_auto_rules(user['username'], rules)
        return {'success': True, 'rules': rules}

    @app.get('/api/web/overview')
    async def overview(user=Depends(current_user)):
        devices = devices_for(user['username'])
        await init_user_db(user['username'])
        since = (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
        async with aiosqlite.connect(f"storage/{user['username']}/history/logs.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT COUNT(*) as total, COALESCE(SUM(date(timestamp)=date('now','localtime')),0) as today FROM logs") as cursor:
                counts = dict(await cursor.fetchone())
            async with db.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 5') as cursor:
                recent = [dict(row) for row in await cursor.fetchall()]
            async with db.execute('SELECT date(timestamp) as day,COUNT(*) as count FROM logs WHERE date(timestamp)>=? GROUP BY day', (since,)) as cursor:
                days = {row['day']: row['count'] for row in await cursor.fetchall()}
        daily = [{'date': (datetime.now() - timedelta(days=offset)).strftime('%Y-%m-%d'),
                  'count': days.get((datetime.now() - timedelta(days=offset)).strftime('%Y-%m-%d'), 0)} for offset in range(6, -1, -1)]
        return {'devices': devices, 'connected': sum(d['online'] for d in devices), 'messages': counts['total'], 'today': counts['today'], 'recent': recent, 'daily': daily}

    @app.get('/api/web/logs')
    async def logs(search: str = '', page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
        await init_user_db(user['username'])
        where = 'WHERE receiver LIKE ? OR message LIKE ? OR sender LIKE ?' if search else ''
        args = [f'%{search}%'] * 3 if search else []
        async with aiosqlite.connect(f"storage/{user['username']}/history/logs.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(f'SELECT COUNT(*) FROM logs {where}', args) as cursor:
                total = (await cursor.fetchone())[0]
            async with db.execute(f'SELECT * FROM logs {where} ORDER BY id DESC LIMIT ? OFFSET ?', [*args, limit, (page-1)*limit]) as cursor:
                rows = [dict(row) for row in await cursor.fetchall()]
        return {'rows': rows, 'total': total, 'page': page, 'limit': limit}

    # Serve only the known SPA routes; missing API routes must remain real 404s.
    dist = PROJECT_ROOT / 'frontend' / 'dist'
    app.mount('/assets', StaticFiles(directory=str(dist / 'assets'), check_dir=False), name='frontend-assets')

    @app.get('/favicon.svg', include_in_schema=False)
    async def favicon():
        return FileResponse(dist / 'favicon.svg', media_type='image/svg+xml')

    async def index():
        if not (dist / 'index.html').exists():
            raise HTTPException(503, 'Frontend belum dibangun. Jalankan npm run build di folder frontend.')
        return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-cache'})

    for route in ['/', '/login', '/register', '/devices', '/wa-profile', '/tools', '/airich', '/auto-reply', '/customer-service', '/logs', '/blast', '/settings', '/channels']:
        app.add_api_route(route, index, methods=['GET'], include_in_schema=False)
