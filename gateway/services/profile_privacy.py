"""Per-device auto-read preferences and WhatsApp privacy operations."""
import asyncio
import logging
import os
from pathlib import Path

from neonize.utils.enum import PrivacySetting, PrivacySettingType, ReceiptType

from gateway.messages.profile_models import ProfilePreferences
from gateway.services.profile import apply_profile_change
from gateway.whatsapp.addressing import normalize_phone_number

preferences: dict[tuple[str, str], ProfilePreferences] = {}
PRIVACY_FIELDS = {
    "read_receipts": (PrivacySettingType.READ_RECEIPTS, "ReadReceipts"),
    "last_seen": (PrivacySettingType.LAST_SEEN, "LastSeen"),
    "online": (PrivacySettingType.ONLINE, "Online"),
    "profile_photo": (PrivacySettingType.PROFILE, "Profile"),
    "group_add": (PrivacySettingType.GROUP_ADD, "GroupAdd"),
    "calls": (PrivacySettingType.CALL_ADD, "CallAdd"),
}


def get_preferences(username: str, phone: str) -> ProfilePreferences:
    key = (username, normalize_phone_number(phone))
    if key not in preferences:
        path = Path("storage") / username / "config" / f"profile_{key[1]}.json"
        try:
            preferences[key] = ProfilePreferences.model_validate_json(path.read_text())
        except FileNotFoundError:
            preferences[key] = ProfilePreferences()
        except (ValueError, OSError):
            logging.getLogger(__name__).warning("Cannot load auto-read preferences for %s:%s", *key)
            preferences[key] = ProfilePreferences()
    return preferences[key]


def save_preferences(username: str, phone: str, value: ProfilePreferences):
    key = (username, normalize_phone_number(phone))
    path = Path("storage") / username / "config" / f"profile_{key[1]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as target:
        target.write(value.model_dump_json())
        target.flush(); os.fsync(target.fileno())
    temporary.replace(path)
    preferences[key] = value


async def read_privacy(client, username: str, phone: str):
    result = {"preferences": get_preferences(username, phone).model_dump(), "privacy": {}, "warnings": []}
    try:
        values = await asyncio.wait_for(client.get_privacy_settings(), timeout=10)
        for name, (_, field) in PRIVACY_FIELDS.items():
            descriptor = values.DESCRIPTOR.fields_by_name[field].enum_type
            enum_value = descriptor.values_by_number.get(getattr(values, field))
            wire_value = enum_value.name.lower() if enum_value else ""
            if wire_value == "contact_blacklist":
                wire_value = "contacts_blacklist"
            result["privacy"][name] = "" if wire_value == "undefined" else wire_value
    except Exception:
        result["warnings"].append("Privasi WhatsApp belum dapat dimuat. Muat ulang untuk melihat nilai terkini.")
    return result


async def set_privacy(client, setting: str, value: str):
    await apply_profile_change(client.set_privacy_setting, PRIVACY_FIELDS[setting][0], PrivacySetting(value))


async def auto_read_message(client, username: str, phone: str, message):
    if getattr(message, "from_me", False) or getattr(message, "is_edit", False):
        return
    chat = getattr(message, "chat", None)
    server = getattr(chat, "Server", "")
    if server not in ("s.whatsapp.net", "lid", "g.us"):
        return
    value = get_preferences(username, phone)
    if not value.auto_read or (server == "g.us" and value.auto_read_scope != "all"):
        return
    message_id = getattr(getattr(message, "info", None), "ID", "")
    if not message_id:
        return
    try:
        # Whatsmeow converts READ to READ_SELF when read receipts are disabled.
        # Do not force a receipt type that could override the user's live privacy.
        await asyncio.wait_for(client.mark_read(message_id, chat=chat, sender=message.sender, receipt=ReceiptType.READ), timeout=8)
    except Exception:
        logging.getLogger(__name__).warning("Auto-read failed for %s:%s; reply handling continues", username, phone)
