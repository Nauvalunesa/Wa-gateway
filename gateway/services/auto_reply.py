"""Per-account auto-reply persistence, matching, and cooldowns."""
import json
import logging
import os
import time
from typing import Any, Dict, List

from gateway.database import log_message
from gateway.messages.airich import build_airich_message
from gateway.messages.models import AIRichPayload
from gateway.state import airich_auto_last, airich_auto_rules, airich_auto_seen


def get_airich_auto_rules(username: str) -> List[Dict[str, Any]]:
    if username not in airich_auto_rules:
        path = os.path.join("storage", username, "config", "airich_auto_replies.json")
        try:
            with open(path, encoding="utf-8") as source:
                saved = json.load(source)
            airich_auto_rules[username] = saved if isinstance(saved, list) else []
        except FileNotFoundError:
            airich_auto_rules[username] = []
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("Could not load AI Rich auto-replies for %s: %s", username, exc)
            airich_auto_rules[username] = []
    return airich_auto_rules[username]


def save_airich_auto_rules(username: str, rules: List[Dict[str, Any]]) -> None:
    path = os.path.join("storage", username, "config", "airich_auto_replies.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as destination:
        json.dump(rules, destination, ensure_ascii=False)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)
    airich_auto_rules[username] = rules


async def try_airich_auto_reply(client, username: str, phone: str, message) -> bool:
    """Send the first matching per-account AI Rich rule for an incoming chat message."""
    text = (getattr(message, "text", "") or "").strip()
    if not text or getattr(message, "is_edit", False):
        return False
    server = getattr(getattr(message, "chat", None), "Server", "")
    if server not in ("s.whatsapp.net", "g.us"):
        return False
    chat_id = f"{message.chat.User}@{server}"
    normalized = text.casefold()
    for rule in get_airich_auto_rules(username):
        if not rule.get("enabled", True):
            continue
        keyword = str(rule.get("keyword", "")).strip().casefold()
        if not keyword:
            continue
        matched = normalized == keyword if rule.get("match") == "exact" else keyword in normalized
        if not matched:
            continue
        scope = rule.get("scope", "all")
        if scope == "private" and server != "s.whatsapp.net":
            continue
        if scope == "group" and server != "g.us":
            continue
        rule_id = str(rule.get("id", keyword))
        cooldown_key = (f"{username}:{phone}", chat_id, rule_id)
        now = time.monotonic()
        cooldown = max(0, min(86400, int(rule.get("cooldown_seconds", 30))))
        if cooldown and now - airich_auto_last.get(cooldown_key, 0) < cooldown:
            continue
        message_id = str(getattr(getattr(message, "info", None), "ID", ""))
        seen_key = f"{username}:{phone}:{message_id}" if message_id else ""
        if seen_key and seen_key in airich_auto_seen:
            return False
        if seen_key:
            airich_auto_seen[seen_key] = now
        if len(airich_auto_seen) > 5000:
            for key, seen_at in list(airich_auto_seen.items()):
                if now - seen_at > 3600 or len(airich_auto_seen) > 4000:
                    airich_auto_seen.pop(key, None)
        data = AIRichPayload(
            to=chat_id,
            phone=phone,
            blocks=rule["blocks"],
        )
        rich_message = await build_airich_message(data, client)
        await client.send_message(message.chat, rich_message)
        if cooldown:
            airich_auto_last[cooldown_key] = now
        await log_message(username, f"DEVICE({phone})", chat_id, f"[AI RICH AUTO REPLY] {keyword}", "OUTGOING")
        return True
    return False
