"""Groups API routes."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from gateway.security import verify_api_key
from gateway.whatsapp.clients import get_client
from gateway.whatsapp.serialization import str_to_jid


router = APIRouter()


@router.get("/api/groups")
async def api_get_groups(phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Get list of joined groups"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    # Ensure client is connected
    status = client.is_connected
    if asyncio.iscoroutine(status): status = await status
    if not status:
        raise HTTPException(status_code=503, detail="Client is initialized but not connected to WA servers")

    try:
        print(f"🔍 Fetching groups for {p}...")
        groups = await client.get_joined_groups()
        res = []

        if groups:
            # Handle RepeatedCompositeContainer or list
            try:
                for g in groups:
                    try:
                        if hasattr(g, 'JID') and g.JID:
                            jid_str = str(f"{g.JID.User}@{g.JID.Server}")
                        else:
                            jid_str = str(getattr(g, 'jid', ''))

                        if not jid_str or jid_str == "None": continue

                        # Bersihkan Nama dari metadata protobuf
                        name_raw = getattr(g, 'Name', '') or getattr(g, 'GroupName', '') or jid_str
                        name_str = str(name_raw)
                        if 'Name: "' in name_str:
                            import re
                            match = re.search(r'Name: "([^"]+)"', name_str)
                            if match: name_str = match.group(1)

                        res.append({
                            "jid": str(jid_str),
                            "name": name_str,
                            "is_parent": bool(getattr(g, 'IsParentGroup', False)),
                            "is_community": bool(getattr(g, 'IsCommunity', False))
                        })
                    except: continue
            except TypeError:
                group_list = getattr(groups, 'GroupInfo', []) or getattr(groups, 'Groups', []) or []
                for g in group_list:
                    try:
                        if hasattr(g, 'JID') and g.JID:
                            jid_str = str(f"{g.JID.User}@{g.JID.Server}")
                        else:
                            jid_str = str(getattr(g, 'jid', ''))

                        name_raw = getattr(g, 'Name', '') or getattr(g, 'GroupName', '') or jid_str
                        name_str = str(name_raw)
                        if 'Name: "' in name_str:
                            import re
                            match = re.search(r'Name: "([^"]+)"', name_str)
                            if match: name_str = match.group(1)

                        res.append({
                            "jid": str(jid_str),
                            "name": name_str,
                            "is_parent": bool(getattr(g, 'IsParentGroup', False)),
                            "is_community": bool(getattr(g, 'IsCommunity', False))
                        })
                    except: continue

        return {"success": True, "groups": res, "count": len(res), "device": p}
    except Exception as e:
        print(f"❌ Error in api_get_groups: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch groups: {str(e)}")


@router.get("/api/group-info")
async def api_group_info(group_jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Get group metadata and participants with LID to PN conversion"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    status = client.is_connected
    if asyncio.iscoroutine(status): status = await status
    if not status:
        raise HTTPException(status_code=503, detail="Client is initialized but not connected to WA servers")

    try:
        info = await client.get_group_info(str_to_jid(group_jid))
        participants = []
        for p_member in info.Participants:
            orig_jid = f"{p_member.JID.User}@{p_member.JID.Server}"
            final_jid = orig_jid

            # Jika peserta pakai LID, coba konversi ke nomor HP
            if p_member.JID.Server == "lid":
                try:
                    res = await client.get_pn_from_lid(p_member.JID)
                    if res:
                        final_jid = f"{res.User}@{res.Server}"
                except: pass

            participants.append({
                "jid": final_jid,
                "lid": orig_jid if p_member.JID.Server == "lid" else None,
                "is_admin": bool(p_member.IsAdmin),
                "is_super_admin": bool(p_member.IsSuperAdmin)
            })

        # Ambil nama grup secara aman dari info.GroupName
        group_name = group_jid
        group_name_obj = getattr(info, 'GroupName', None)
        if group_name_obj:
            if isinstance(group_name_obj, str):
                group_name = group_name_obj
            else:
                group_name = getattr(group_name_obj, 'Name', group_jid)

        # Bersihkan jika masih ada metadata string
        group_name = str(group_name)
        if 'Name: "' in group_name:
            import re
            match = re.search(r'Name: "([^"]+)"', group_name)
            if match: group_name = match.group(1)

        return {
            "success": True,
            "jid": group_jid,
            "name": group_name,
            "owner": f"{info.OwnerJID.User}@{info.OwnerJID.Server}" if hasattr(info, 'OwnerJID') and info.OwnerJID.User else None,
            "participants": participants,
            "device": p
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
