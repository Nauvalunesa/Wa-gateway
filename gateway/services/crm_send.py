"""Send raw protobuf messages; no eval, exec, or shell execution."""
import asyncio
import re
from fastapi import HTTPException
from neonize.utils import build_jid
from gateway.messages.crm_models import validate_raw
from gateway.services import crm
from gateway.database import log_message


def destination(value):
    value=value.strip()
    if '@' not in value:
        value=value.lstrip('+')+'@s.whatsapp.net'
    user,_,server=value.partition('@')
    pattern=r'[1-9][0-9-]{5,30}' if server=='g.us' else r'[1-9][0-9]{6,19}'
    if server not in ('s.whatsapp.net','lid','g.us') or not re.fullmatch(pattern,user):
        raise HTTPException(422,'Tujuan harus nomor berkode negara atau JID grup/chat pribadi')
    return build_jid(user,server=server)


async def run_item(client,username,item,phone,to,request_id):
    jid=destination(to); message=validate_raw(item['payload'])
    claimed,status=await crm.claim_execution(username,item['id'],request_id)
    if not claimed:
        return {'success':status=='sent','duplicate':True,'status':status,'request_id':request_id,
                'message':f'Permintaan sebelumnya berstatus {status}. Tidak dikirim ulang; periksa WhatsApp dahulu.'}
    try:
        await asyncio.wait_for(client.send_message(jid,message),timeout=30)
    except asyncio.TimeoutError as exc:
        await crm.finish_execution(username,request_id,'uncertain','Timeout')
        raise HTTPException(504,'Pengiriman timeout; hasil belum pasti. Jangan ulang otomatis, periksa WhatsApp dahulu.') from exc
    except Exception as exc:
        await crm.finish_execution(username,request_id,'failed',str(exc)[:500])
        raise HTTPException(502,f'Pengiriman raw message gagal: {exc}') from exc
    await crm.finish_execution(username,request_id,'sent')
    await log_message(username,f'DEVICE({phone})',f'{jid.User}@{jid.Server}',f'[CRM RAW] {item["name"]}','OUTGOING')
    return {'success':True,'status':'sent','request_id':request_id}
