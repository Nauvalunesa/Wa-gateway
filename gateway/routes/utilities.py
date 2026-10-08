"""Utilities API routes."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from gateway.security import verify_api_key
from gateway.whatsapp.addressing import normalize_wa
from gateway.whatsapp.clients import get_client
from gateway.whatsapp.serialization import str_to_jid


router = APIRouter()


@router.get("/api/convert-jid")
async def api_convert_jid(jid: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """
    External API: Convert JID between LID and PN.
    If PN JID provided, returns LID JID.
    If LID JID provided, returns PN JID.
    """
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    # Ensure client is connected
    status = client.is_connected
    if asyncio.iscoroutine(status): status = await status
    if not status:
        raise HTTPException(status_code=503, detail="Client is initialized but not connected to WA servers")

    try:
        target = str_to_jid(jid)
        res_jid = None

        if target.Server == "lid":
            # Convert LID to PN
            res = await client.get_pn_from_lid(target)
            if res:
                res_jid = f"{res.User}@{res.Server}"
        else:
            # Convert PN to LID
            res = await client.get_lid_from_pn(target)
            if res:
                res_jid = f"{res.User}@{res.Server}"

        return {
            "success": True,
            "input": jid,
            "result": res_jid,
            "device": p
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/check-number")
async def api_check_number(phone_to_check: str, phone: Optional[str] = None, username: str = Depends(verify_api_key)):
    """External API: Check if a number is registered on WhatsApp and get ALL available profile info from neonize"""
    client, p = get_client(username, phone)
    if not client:
        raise HTTPException(status_code=503, detail="WhatsApp client is not connected")

    clean_phone = normalize_wa(phone_to_check)
    try:
        # 1. Basic Check & Primary JID
        res = await client.is_on_whatsapp(clean_phone)
        if not res or not res[0].IsIn:
            return {"success": True, "phone": phone_to_check, "is_registered": False, "device": p}

        actual_jid = res[0].JID
        jid_str = f"{actual_jid.User}@{actual_jid.Server}"

        # 2. Get LID (Identity JID) or PN JID
        lid_jid = None
        pn_jid = jid_str if actual_jid.Server == "s.whatsapp.net" else None

        try:
            if actual_jid.Server == "s.whatsapp.net":
                lid_res = await client.get_lid_from_pn(actual_jid)
                if lid_res: lid_jid = f"{lid_res.User}@{lid_res.Server}"
            elif actual_jid.Server == "lid":
                lid_jid = jid_str
                pn_res = await client.get_pn_from_lid(actual_jid)
                if pn_res: pn_jid = f"{pn_res.User}@{pn_res.Server}"
        except: pass

        # 3. Get User Info (Status, Verified Name Details)
        status_text = ""
        pushname = ""
        is_verified = False
        verified_details = {}
        linked_devices = []

        # Check verified name from is_on_whatsapp first
        try:
            v_name_initial = getattr(res[0], 'VerifiedName', None)
            if v_name_initial:
                d_initial = getattr(v_name_initial, 'Details', None)
                v_name_str = getattr(d_initial, 'verifiedName', "") if d_initial else ""
                if v_name_str:
                    pushname = v_name_str
                    is_verified = True
                    verified_details = {
                        "issuer": getattr(d_initial, 'issuer', ""),
                        "serial": getattr(d_initial, 'serial', 0),
                        "issue_time": getattr(d_initial, 'issueTime', 0),
                        "localized_names": []
                    }
        except:
            pass

        try:
            info_res = await client.get_user_info(actual_jid)
            if info_res:
                user_infos = getattr(info_res, 'UsersInfo', info_res) if hasattr(info_res, 'UsersInfo') else info_res

                if user_infos and len(user_infos) > 0:
                    u_info = getattr(user_infos[0], 'UserInfo', None)
                    if u_info:
                        status_text = getattr(u_info, 'Status', "")

                        # Update verified info if more details found
                        v_name = getattr(u_info, 'VerifiedName', None)
                        if v_name:
                            cert = getattr(v_name, 'Certificate', None)
                            d = getattr(cert, 'Details', getattr(v_name, 'Details', None)) if cert else getattr(v_name, 'Details', None)
                            v_name_str = getattr(d, 'verifiedName', "") if d else ""
                            if v_name_str:
                                pushname = v_name_str
                                is_verified = True
                                verified_details = {
                                    "issuer": getattr(d, 'issuer', ""),
                                    "serial": getattr(d, 'serial', 0),
                                    "issue_time": getattr(d, 'issueTime', 0),
                                    "localized_names": [getattr(l, 'verifiedName', "") for l in getattr(d, 'localizedNames', [])]
                                }

                        # Linked Devices
                        devs = getattr(u_info, 'Devices', [])
                        for dev in devs:
                            linked_devices.append({
                                "jid": f"{dev.User}@{dev.Server}",
                                "device_id": dev.Device,
                                "is_companion": dev.Device > 0
                            })
        except Exception as e:
            print(f"⚠️ Failed to get extended user info: {e}")

        # 4. Get Profile Picture (Full Info)
        pp_info = {}
        try:
            pp_res = await client.get_profile_picture(actual_jid)
            if pp_res:
                pp_info = {
                    "url": getattr(pp_res, 'URL', ''),
                    "id": getattr(pp_res, 'ID', ''),
                    "type": getattr(pp_res, 'Type', ''),
                    "direct_path": getattr(pp_res, 'DirectPath', '')
                }
        except: pass

        return {
            "success": True,
            "phone": phone_to_check,
            "is_registered": True,
            "jid": pn_jid or jid_str,
            "lid": lid_jid,
            "info": {
                "pushname": pushname,
                "status": status_text,
                "is_verified": is_verified,
                "verified_details": verified_details,
                "devices": linked_devices
            },
            "profile_picture": pp_info,
            "device_used": p
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
