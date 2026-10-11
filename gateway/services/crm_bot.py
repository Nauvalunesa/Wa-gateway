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

_EXPORT_PART = re.compile(r'Part\s+(\d+)\s*/\s*(\d+)', re.IGNORECASE)


def normalize_proto_json(data,descriptor):
    """Accept equivalent camel-case acronym spellings found in WhatsApp exports."""
    if isinstance(data,list):return [normalize_proto_json(value,descriptor) for value in data]
    if not isinstance(data,dict):return data
    fields={field.name.lower():field for field in descriptor.fields}
    result={}
    for key,value in data.items():
        field=descriptor.fields_by_name.get(key) or fields.get(key.lower())
        if field is None:
            result[key]=value
        elif field.message_type is None:
            if isinstance(value,dict) and {'low','high'}<=value.keys():
                value=(int(value['high'])<<32)|(int(value['low'])&0xffffffff)
            result[field.name]=value
        elif field.message_type.GetOptions().map_entry and isinstance(value,dict):
            value_field=field.message_type.fields_by_name['value']
            result[field.name]={item:(normalize_proto_json(child,value_field.message_type)
                if value_field.message_type else child) for item,child in value.items()}
        else:
            result[field.name]=normalize_proto_json(value,field.message_type)
    return result


def export_messages(text):
    """Read protobuf Message objects embedded in a chat-export JSON fragment."""
    candidates=[]
    decoder=json.JSONDecoder()
    for match in re.finditer(r'"message"\s*:\s*',text):
        try:
            record,_=decoder.raw_decode(text[match.end():])
            if not isinstance(record,dict):continue
            visible={key:value for key,value in record.items() if key not in (
                'messageContextInfo','protocolMessage','senderKeyDistributionMessage','keepInChatMessage')}
            if not visible:continue
            protobuf=validate_raw(normalize_proto_json(record,Message.DESCRIPTOR))
            if protobuf.ListFields():candidates.append(protobuf)
        except (json.JSONDecodeError,ValueError,TypeError):
            continue
    # A text export can repeat the same record in adjacent chunks.
    unique=[];seen=set()
    for message in candidates:
        signature=message.SerializeToString(deterministic=True)
        if signature not in seen:seen.add(signature);unique.append(message)
    return unique[:10]


def raw_title(raw):
    fields=raw.ListFields()
    return fields[0][0].name if fields else 'Raw message'


async def send_draft_result(client,owner,draft):
    payload=draft['payload']
    encoded=json.dumps(payload,ensure_ascii=False,indent=2)
    if len(encoded)<=3500:
        await client.send_message(owner,Message(conversation='*CRM • Raw Message*\n```'+encoded+'```'))
    else:
        await client.send_document(owner,encoded.encode(),filename='raw-message.json',mimetype='application/json',caption='CRM • JSON pesan yang dipilih')
    content={'title':'CRM • Raw Message','body':f'{draft["name"]}\nJalankan mengirim pesan yang dipilih ke chat asal:\n{draft["source_chat"]}\n\nSimpan ke DB dan Tambah ke Aksi menyimpan pesan sebagai data.',
             'footer':'utusan.chat • Hanya owner','mode':'buttons','options':[
                 {'id':f'crm:{draft["id"]}:run','label':'Jalankan'},
                 {'id':f'crm:{draft["id"]}:save','label':'Simpan ke DB'},
                 {'id':f'crm:{draft["id"]}:action','label':'Tambah ke Aksi'}]}
    try:await client.send_message(owner,await build_cs_message(content,client))
    except Exception:
        await client.send_message(owner,Message(conversation=content['body']+f'\n\ncrm jalankan {draft["id"]}\ncrm simpan {draft["id"]}\ncrm aksi {draft["id"]}'))


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
            if quoted.HasField('conversation') and _EXPORT_PART.search(quoted.conversation):
                part=_EXPORT_PART.search(quoted.conversation)
                candidates=export_messages(quoted.conversation)
                if not candidates:
                    await notify(f'File ini baru potongan Part {part.group(1)}/{part.group(2)}. JSON-nya belum lengkap untuk membangun ulang pesan. Kirim/reply satu objek message protobuf lengkap, lalu ketik crm lagi.')
                    return True
                if len(candidates)==1:
                    payload=MessageToDict(candidates[0]);event_id=str(getattr(getattr(message,'info',None),'ID',''))
                    if not event_id:raise HTTPException(422,'ID pesan CRM tidak tersedia')
                    draft=await crm.create_item(username,f'Raw {raw_title(candidates[0])}','draft',payload,phone,owner_id,f'{message.chat.User}@{message.chat.Server}',event_id)
                    await send_draft_result(client,owner,draft);return True
                event_id=str(getattr(getattr(message,'info',None),'ID',''))
                if not event_id:raise HTTPException(422,'ID pesan CRM tidak tersedia')
                drafts=[]
                for index,raw_message in enumerate(candidates):
                    payload=MessageToDict(raw_message)
                    draft=await crm.create_item(username,f'Pesan {index+1} • {raw_title(raw_message)}','draft',payload,
                        phone,owner_id,f'{message.chat.User}@{message.chat.Server}',f'{event_id}_{index}')
                    fields=raw_message.ListFields();value=fields[0][1] if fields else None
                    preview=(getattr(value,'text','') or getattr(value,'caption','') or '').strip()
                    label=f'{index+1}. {raw_title(raw_message)}'+(f' · {preview[:30]}' if preview else '')
                    drafts.append({'id':draft['id'],'label':label[:72]})
                content={'title':'Pilih pesan dari JSON','body':f'Potongan Part {part.group(1)}/{part.group(2)} memuat {len(drafts)} pesan WhatsApp yang bisa dibangun ulang. Pilih satu untuk melihat JSON dan tombol kirim.',
                    'footer':'Pesan tidak dikirim sebelum tombol Jalankan ditekan.','mode':'list','options':[
                        {'id':f'crm:{draft["id"]}:choose','label':draft['label']} for draft in drafts]}
                await client.send_message(owner,await build_cs_message(content,client));return True
            payload=MessageToDict(quoted)
            validate_raw(payload)
            event_id=str(getattr(getattr(message,'info',None),'ID',''))
            if not event_id: raise HTTPException(422,'ID pesan CRM tidak tersedia')
            source_chat=f'{message.chat.User}@{message.chat.Server}'
            draft=await crm.create_item(username,f'Raw {raw_title(quoted)}','draft',payload,phone,owner_id,source_chat,event_id)
            await send_draft_result(client,owner,draft)
            return True
        match=re.fullmatch(r'crm:([a-f0-9]{32}):(run|save|action|choose)',value)
        if match: item_id,operation=match.groups()
        else:
            match=re.fullmatch(r'crm (jalankan|simpan|aksi) ([a-f0-9]{32})',value.casefold())
            if not match:
                await notify('Gunakan reply pesan + crm, atau tekan tombol pada hasil CRM.');return True
            command,item_id=match.groups();operation={'jalankan':'run','simpan':'save','aksi':'action'}[command]
        item=await crm.get_item(username,item_id,phone,owner_id)
        if item['kind']!='draft': raise HTTPException(404,'Tombol CRM tidak valid')
        if operation=='choose':
            await send_draft_result(client,owner,item);return True
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
