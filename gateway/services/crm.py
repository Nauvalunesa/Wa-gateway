"""Per-account raw-message storage and idempotent execution claims."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
import aiosqlite
from fastapi import HTTPException


def timestamp(): return datetime.now(timezone.utc).isoformat(timespec='seconds')


@asynccontextmanager
async def database(username):
    path = Path('storage') / username / 'crm'
    path.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path / 'raw.sqlite3', timeout=10) as db:
        db.row_factory = aiosqlite.Row
        await db.execute('''CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL,
            device TEXT NOT NULL, owner_jid TEXT NOT NULL, source_chat TEXT NOT NULL,
            event_id TEXT, parent_id TEXT, created_at TEXT NOT NULL, expires_at REAL,
            UNIQUE(device,event_id), UNIQUE(parent_id,kind))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,item_id TEXT NOT NULL,status TEXT NOT NULL,error TEXT,
            created_at TEXT NOT NULL)''')
        await db.commit()
        yield db


def unpack(row):
    item = dict(row); item['payload'] = json.loads(item['payload']); return item


async def get_item(username, item_id, device=None, owner_jid=None):
    async with database(username) as db:
        async with db.execute('SELECT * FROM items WHERE id=?', (item_id,)) as cursor: row = await cursor.fetchone()
    if not row or (row['expires_at'] and row['expires_at'] < time.time()) or (device is not None and (row['device'] != device or row['owner_jid'] != owner_jid)):
        raise HTTPException(404, 'Raw message tidak ditemukan, kedaluwarsa, atau bukan milik Anda')
    return unpack(row)


async def create_item(username, name, kind, payload, device='', owner_jid='', source_chat='', event_id=None, parent_id=None):
    item_id = uuid.uuid4().hex
    async with database(username) as db:
        await db.execute('DELETE FROM items WHERE kind=\'draft\' AND expires_at<?', (time.time(),))
        await db.execute('''INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                         (item_id, kind, name, json.dumps(payload, ensure_ascii=False), device, owner_jid, source_chat, event_id, parent_id, timestamp(), time.time()+900 if kind=='draft' else None))
        await db.commit()
        if event_id:
            async with db.execute('SELECT id FROM items WHERE device=? AND event_id=?', (device,event_id)) as cursor: item_id = (await cursor.fetchone())[0]
        elif parent_id:
            async with db.execute('SELECT id FROM items WHERE parent_id=? AND kind=?', (parent_id,kind)) as cursor: item_id = (await cursor.fetchone())[0]
    return await get_item(username,item_id)


async def list_items(username, kind, page):
    async with database(username) as db:
        where = "kind=?" if kind else "kind IN ('saved','action')"
        args = [kind] if kind else []
        async with db.execute('SELECT COUNT(*) FROM items WHERE '+where,args) as c: total=(await c.fetchone())[0]
        async with db.execute('SELECT * FROM items WHERE '+where+' ORDER BY created_at DESC,id LIMIT 20 OFFSET ?',[*args,(page-1)*20]) as c: items=[unpack(row) for row in await c.fetchall()]
    return {'items':items,'total':total,'page':page,'page_size':20}


async def delete_item(username,item_id):
    async with database(username) as db:
        cursor=await db.execute("DELETE FROM items WHERE id=? AND kind!='draft'",(item_id,))
        if not cursor.rowcount: raise HTTPException(404,'Raw message tidak ditemukan')
        await db.commit()


async def claim_execution(username,item_id,request_id):
    async with database(username) as db:
        await db.execute('BEGIN IMMEDIATE')
        async with db.execute('SELECT item_id,status FROM executions WHERE id=?',(request_id,)) as c: previous=await c.fetchone()
        if previous:
            if previous['item_id']!=item_id: raise HTTPException(409,'ID request sudah digunakan untuk pesan lain')
            return False,previous['status']
        await db.execute('INSERT INTO executions VALUES (?,?,?,?,?)',(request_id,item_id,'sending',None,timestamp()))
        await db.commit()
    return True,'sending'


async def finish_execution(username,request_id,status,error=None):
    async with database(username) as db:
        await db.execute('UPDATE executions SET status=?,error=? WHERE id=?',(status,error,request_id)); await db.commit()
