"""Request an official Neonize pairing code and retain the resulting session."""
import asyncio
import sys
from pathlib import Path

from neonize.aioze.client import NewAClient
from neonize.aioze.events import ConnectedEv


async def manual_pair(phone: str):
    phone = ''.join(c for c in phone if c.isdigit())
    if not 8 <= len(phone) <= 15:
        raise ValueError('Invalid phone number')
    session = Path('storage/manual-pair/sessions') / f'{phone}.sqlite3'
    session.parent.mkdir(parents=True, exist_ok=True)
    client = NewAClient(str(session))
    ready = asyncio.Event()
    connected = asyncio.Event()

    @client.qr
    async def on_qr(client, qr):
        ready.set()

    @client.event(ConnectedEv)
    async def on_connected(client, event):
        print('CONNECTED', flush=True)
        connected.set()
        ready.set()

    task = await client.connect()
    try:
        await asyncio.wait_for(ready.wait(), timeout=45)
        if not connected.is_set():
            code = await asyncio.wait_for(client.PairPhone(phone, show_push_notification=True), timeout=45)
            if not code:
                raise RuntimeError('WhatsApp returned an empty pairing code')
            print(f'PAIRING_CODE={code}', flush=True)
            print('Waiting up to 180 seconds for confirmation on the phone.', flush=True)
            await asyncio.wait_for(connected.wait(), timeout=180)
        print(f'SESSION_SAVED={session}', flush=True)
    finally:
        await client.stop()
        await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: .venv312/bin/python manual_pair.py PHONE')
    asyncio.run(manual_pair(sys.argv[1]))
