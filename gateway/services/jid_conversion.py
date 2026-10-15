"""Resolve PN/LID pairs through the active device's Neonize mapping store."""
import asyncio
from fastapi import HTTPException
from gateway.services.crm_send import destination


async def convert_jid(client,value):
    target=destination(value)
    if target.Server not in ('s.whatsapp.net','lid'):
        raise HTTPException(422,'Konversi hanya untuk JID nomor (@s.whatsapp.net) dan LID (@lid)')
    expected='s.whatsapp.net' if target.Server=='lid' else 'lid'
    method=client.get_pn_from_lid if target.Server=='lid' else client.get_lid_from_pn
    try: result=await asyncio.wait_for(method(target),timeout=10)
    except asyncio.TimeoutError as exc:raise HTTPException(504,'Konversi JID timeout; coba lagi saat perangkat online') from exc
    except Exception as exc:raise HTTPException(502,'Gagal membaca mapping JID dari perangkat') from exc
    if not result or not result.User or result.Server!=expected:
        raise HTTPException(404,'Mapping nomor/LID belum tersedia di perangkat ini. Gunakan perangkat yang pernah berinteraksi dengan nomor tersebut.')
    return {'success':True,'input':f'{target.User}@{target.Server}','result':f'{result.User}@{result.Server}',
            'direction':'LID → PN' if target.Server=='lid' else 'PN → LID'}
