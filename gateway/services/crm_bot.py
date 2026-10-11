"""CRM: inspect quoted raw messages, accessible only through the linked owner."""
import json
import re
from google.protobuf.json_format import MessageToDict
from fastapi import HTTPException
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
from gateway.messages.crm_models import validate_raw
from gateway.messages.cs import build_cs_message
from gateway.services import crm
from gateway.services.crm_send import run_item
from gateway.services.customer_service import selected_input
from gateway.services.crm_access import crm_owner


def quoted_raw(message):
    # Preserve the complete quoted protobuf, including view-once wrappers.
    raw=getattr(message,'_real_msg',None)
    if raw is not None:
        for _,value in raw.ListFields():
            context=getattr(value,'contextInfo',None)
            if context is not None and context.quotedMessage.ListFields():
                return context.quotedMessage
        return None
    try:return message.quoted.message if message.quoted else None
    except (ValueError,IndexError,AttributeError):return None


async def try_raw_crm(client,username,phone,message):
    if getattr(message,'is_edit',False): return False
    if getattr(message.chat,'Server','') not in ('s.whatsapp.net','lid','g.us'): return False
    value=selected_input(message).strip()
    if value.casefold()!='crm' and not value.startswith('crm:') and not value.casefold().startswith('crm '): return False
    owner=await crm_owner(client,username,phone,message)
    if owner is None:return False
    owner_id=f'{owner.User}@{owner.Server}'
    async def notify(text):
        await client.send_message(owner,Message(conversation=text))
    try:
        if value.casefold()=='crm':
            quoted=quoted_raw(message)
            if quoted is None:
                await notify('Reply pesan yang ingin diambil raw JSON-nya, lalu ketik crm. Hasil hanya dikirim ke chat pribadi owner yang meminta.');return True
            payload=MessageToDict(quoted)
            validate_raw(payload)
            event_id=str(getattr(getattr(message,'info',None),'ID',''))
            if not event_id: raise HTTPException(422,'ID pesan CRM tidak tersedia')
            source_chat=f'{message.chat.User}@{message.chat.Server}'
            draft=await crm.create_item(username,f'Raw {quoted.ListFields()[0][0].name}','draft',payload,phone,owner_id,source_chat,event_id)
            encoded=json.dumps(payload,ensure_ascii=False,indent=2)
            if len(encoded)<=3500:
                await notify('*CRM • Raw Message*\n```'+encoded+'```')
            else:
                await client.send_document(owner,encoded.encode(),filename='raw-message.json',mimetype='application/json',caption='CRM • JSON lengkap dari pesan yang di-reply')
            item_id=draft['id']
            content={'title':'CRM • Raw Message','body':f'Hasil siap. Jalankan akan mengirim ulang ke chat asal:\n{source_chat}\n\nSimpan ke DB dan Tambah ke Aksi hanya menyimpan data. Tombol berlaku 15 menit.',
                     'footer':'utusan.chat • Hanya owner','mode':'buttons','options':[
                         {'id':f'crm:{item_id}:run','label':'Jalankan'},
                         {'id':f'crm:{item_id}:save','label':'Simpan ke DB'},
                         {'id':f'crm:{item_id}:action','label':'Tambah ke Aksi'}]}
            try: await client.send_message(owner,await build_cs_message(content,client))
            except Exception:
                await notify(content['body']+f'\n\nJika tombol tidak tersedia:\ncrm jalankan {item_id}\ncrm simpan {item_id}\ncrm aksi {item_id}')
            return True
        match=re.fullmatch(r'crm:([a-f0-9]{32}):(run|save|action)',value)
        if match: item_id,operation=match.groups()
        else:
            match=re.fullmatch(r'crm (jalankan|simpan|aksi) ([a-f0-9]{32})',value.casefold())
            if not match:
                await notify('Gunakan reply pesan + crm, atau tekan tombol pada hasil CRM.');return True
            command,item_id=match.groups();operation={'jalankan':'run','simpan':'save','aksi':'action'}[command]
        item=await crm.get_item(username,item_id,phone,owner_id)
        if item['kind']!='draft': raise HTTPException(404,'Tombol CRM tidak valid')
        if operation=='run':
            result=await run_item(client,username,item,phone,item['source_chat'],'wa_'+item_id)
            await notify('Raw message terkirim ke chat asal.' if result['status']=='sent' and not result.get('duplicate') else f'Permintaan sebelumnya: {result["status"]}. Tidak dikirim ulang otomatis.')
        else:
            kind='saved' if operation=='save' else 'action'
            saved=await crm.create_item(username,item['name'],kind,item['payload'],phone,owner_id,item['source_chat'],parent_id=item_id)
            await notify(('Raw message tersimpan ke database.' if kind=='saved' else 'Raw message ditambahkan ke Aksi.')+f'\nID: {saved["id"]}\nKelola: https://utusan.chat/crm')
    except (HTTPException,ValueError) as exc:
        await notify(str(exc.detail if isinstance(exc,HTTPException) else exc))
    return True
