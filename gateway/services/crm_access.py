"""Account-scoped CRM owners; linked device owner is always authorized."""
import asyncio
import json
from pathlib import Path
import re
import uuid
from neonize.utils import build_jid


def owner_phones(username):
    path=Path('storage')/username/'config'/'crm_owners.json'
    if not path.exists(): return []
    try:
        data=json.loads(path.read_text())
        return [phone for phone in data.get('owners',[]) if isinstance(phone,str) and re.fullmatch(r'[1-9][0-9]{6,19}',phone)]
    except (ValueError,OSError,TypeError,AttributeError): return []


def set_owner_phones(username,phones):
    path=Path('storage')/username/'config'/'crm_owners.json';path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('crm_owners.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps({'owners':list(dict.fromkeys(phones))},indent=2)+'\n')
    temporary.replace(path)
    return owner_phones(username)


async def crm_owner(client,username,phone,message):
    if getattr(message,'from_me',False): return build_jid(phone)
    allowed=owner_phones(username)
    if not allowed:return None
    sender=getattr(message,'sender',None)
    alternate=getattr(message,'sender_alt',None)
    for candidate in (sender,alternate):
        if candidate is not None and candidate.Server=='s.whatsapp.net':
            if candidate.User in allowed:return build_jid(candidate.User)
            return None
    if sender is not None and sender.Server=='lid':
        try:
            resolved=await asyncio.wait_for(client.get_pn_from_lid(sender),timeout=5)
            if resolved.Server=='s.whatsapp.net' and resolved.User in allowed:
                return build_jid(resolved.User,server=resolved.Server)
        except Exception: pass
    return None
