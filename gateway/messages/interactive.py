"""Native-flow payload normalization and validation."""
from copy import deepcopy

from fastapi import HTTPException


def normalize_interactive_payload(payload: dict) -> dict:
    """Accept the former frontend spelling without dropping protobuf validation."""
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(422, "Payload interactive harus berupa objek JSON yang berisi pesan.")
    result = deepcopy(payload)
    header = result.get("header")
    if header is not None:
        if not isinstance(header, dict):
            raise HTTPException(422, "Header interactive harus berupa objek JSON.")
        for field in ("imageMessage", "videoMessage"):
            media = header.get(field)
            if media is not None and not isinstance(media, (dict, str)):
                raise HTTPException(422, f"{field} harus berupa URL atau objek media.")
            if isinstance(media, dict):
                url = media.get("URL") or media.get("url")
                if url is not None and not isinstance(url, str):
                    raise HTTPException(422, "URL media interactive harus berupa teks.")
    flow = result.get("nativeFlowMessage")
    if flow is not None and not isinstance(flow, dict):
        raise HTTPException(422, "nativeFlowMessage harus berupa objek JSON.")
    if isinstance(flow, dict) and "buttons" in flow and not isinstance(flow["buttons"], list):
        raise HTTPException(422, "buttons harus berupa daftar tombol.")
    if isinstance(flow, dict) and "messageParamsJson" in flow:
        flow.setdefault("messageParamsJSON", flow.pop("messageParamsJson"))
    if isinstance(flow, dict) and isinstance(flow.get("buttons"), list):
        for button in flow["buttons"]:
            if not isinstance(button, dict):
                raise HTTPException(422, "Setiap tombol harus berupa objek JSON.")
            if isinstance(button, dict) and "buttonParamsJson" in button:
                legacy = button.pop("buttonParamsJson")
                button.setdefault("buttonParamsJSON", legacy)
    return result
