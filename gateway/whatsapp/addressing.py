"""Phone numbers, JID resolution, and mention expansion."""
from fastapi import HTTPException
from neonize.proto.Neonize_pb2 import JID

from gateway.whatsapp.serialization import str_to_jid


async def get_mentions_list(client, target_jid, mentions_str):
    if not mentions_str:
        return []

    mentioned_jids = []
    # Split by comma for multiple targets
    parts = mentions_str.split(",")

    for p in parts:
        p = p.strip()
        if not p: continue

        # Handle "all" for groups (only if not Status)
        if p.lower() == "all" and target_jid.Server == "g.us":
            try:
                info = await client.get_group_info(target_jid)
                for participant in info.Participants:
                    jid = participant.JID
                    if jid.Server == "lid":
                        try:
                            res = await client.get_pn_from_lid(jid)
                            if res: jid = res
                        except: pass
                    mentioned_jids.append(f"{jid.User}@{jid.Server}")
            except: pass
            continue

        # Handle explicit Group JID (expand it) - THIS IS FOR STATUS GROUP TAGGING
        if "@g.us" in p:
            try:
                g_jid = str_to_jid(p)
                info = await client.get_group_info(g_jid)
                print(f"📢 Expanding {len(info.Participants)} members from group {p} for tagging...")
                for participant in info.Participants:
                    jid = participant.JID
                    # Always try to convert to PN JID for Status mentions to work for non-contacts
                    if jid.Server == "lid":
                        try:
                            res = await client.get_pn_from_lid(jid)
                            if res: jid = res
                        except: pass
                    mentioned_jids.append(f"{jid.User}@{jid.Server}")
            except Exception as e:
                print(f"⚠️ Failed to expand group for mentions: {e}")
            continue

        # Handle individual JID or Phone Number
        if "@" in p:
            mentioned_jids.append(p)
        else:
            mentioned_jids.append(normalize_wa(p) + "@s.whatsapp.net")

    # Return unique list
    final_list = list(set(mentioned_jids))
    print(f"✅ Total unique mentions: {len(final_list)}")
    return final_list


def normalize_wa(num):
    if not num: return ""
    num = str(num).strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(num) > 15: return num

    # If starts with 08, it's definitely Indonesia
    if num.startswith("08"):
        return "62" + num[1:]
    # If starts with 0 but not 08, we still assume Indonesia for this gateway context
    # but more safely:
    if num.startswith("0") and len(num) >= 9:
        return "62" + num[1:]

    return num


def normalize_phone_number(phone: str) -> str:
    number = normalize_wa(phone)
    if not number.isascii() or not number.isdigit() or not 7 <= len(number) <= 15:
        raise HTTPException(422, "Nomor WhatsApp harus berisi 7–15 digit dengan kode negara.")
    return number


def get_target_jid(target: str) -> JID:
    if "@" in target:
        return str_to_jid(target)
    clean_id = target.split(":")[0]
    if len(clean_id) >= 15 and clean_id.startswith("1"):
        jid_str = clean_id + "@lid"
    elif "-" in clean_id:
        jid_str = clean_id + "@g.us"
    else:
        jid_str = normalize_wa(clean_id) + "@s.whatsapp.net"
    return str_to_jid(jid_str)


async def get_actual_jid(client, to: str) -> JID:
    """Resolves a JID or a WhatsApp Channel URL to a valid JID object."""
    if not to: return get_target_jid("")
    if "whatsapp.com/channel/" in to:
        invite_key = to.split("whatsapp.com/channel/")[1].split("/")[0]
        try:
            res = await client.get_newsletter_info_with_invite(invite_key)
            jid_obj = getattr(res, "ID", getattr(res, "JID", None))
            if jid_obj: return jid_obj
            raise Exception("Could not find JID in newsletter info")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Newsletter URL: {str(e)}")
    return get_target_jid(to)
