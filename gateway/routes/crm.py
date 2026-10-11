"""Raw-message storage accessible only to the signed-in account owner."""
from typing import Literal
from fastapi import APIRouter,Depends,Query,HTTPException
from gateway.messages.crm_models import RawItem,RawRun,CRMOwners,JIDConversion
from gateway.services.crm_access import owner_phones,set_owner_phones
from gateway.services.jid_conversion import convert_jid
from gateway.security import dashboard_user
from gateway.services import crm
from gateway.services.crm_send import run_item
from gateway.whatsapp.addressing import normalize_phone_number
from gateway.whatsapp.clients import get_client

router=APIRouter()


@router.get('/api/web/crm/config')
async def config(username:str=Depends(dashboard_user)):
    from pathlib import Path
    linked=[p.stem for p in (Path('storage')/username/'sessions').glob('*.sqlite3')]
    return {'owners':owner_phones(username),'linked_devices':linked}


@router.post('/api/web/crm/config')
async def update_config(data:CRMOwners,username:str=Depends(dashboard_user)):
    return {'success':True,'owners':set_owner_phones(username,data.owners)}


@router.post('/api/web/convert-jid')
async def convert(data:JIDConversion,username:str=Depends(dashboard_user)):
    phone=normalize_phone_number(data.phone);client,_=get_client(username,phone)
    if not client:raise HTTPException(503,'Pilih perangkat WhatsApp milik akun yang online')
    return {**await convert_jid(client,data.jid),'device':phone}


@router.get('/api/web/crm/items')
async def list_items(kind: Literal['saved','action']|None=None,page:int=Query(1,ge=1),username:str=Depends(dashboard_user)):
    return await crm.list_items(username,kind,page)


@router.post('/api/web/crm/items',status_code=201)
async def create_item(data:RawItem,username:str=Depends(dashboard_user)):
    return await crm.create_item(username,data.name,data.kind,data.payload)


@router.get('/api/web/crm/items/{item_id}')
async def get_item(item_id:str,username:str=Depends(dashboard_user)):
    return await crm.get_item(username,item_id)


@router.delete('/api/web/crm/items/{item_id}')
async def delete_item(item_id:str,username:str=Depends(dashboard_user)):
    await crm.delete_item(username,item_id);return {'success':True}


@router.post('/api/web/crm/items/{item_id}/action')
async def add_action(item_id:str,username:str=Depends(dashboard_user)):
    item=await crm.get_item(username,item_id)
    return await crm.create_item(username,item['name'],'action',item['payload'],
                                 item['device'],item['owner_jid'],item['source_chat'],parent_id=item_id)


@router.post('/api/web/crm/items/{item_id}/run')
async def run(item_id:str,data:RawRun,username:str=Depends(dashboard_user)):
    item=await crm.get_item(username,item_id)
    phone=normalize_phone_number(data.phone);client,_=get_client(username,phone)
    if not client: raise HTTPException(503,'Pilih perangkat WhatsApp milik akun yang online')
    return await run_item(client,username,item,phone,data.to,data.request_id)
