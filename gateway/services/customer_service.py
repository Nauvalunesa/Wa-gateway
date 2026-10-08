"""Persistent CS menus and isolated, bounded per-chat conversation state."""
from collections import OrderedDict
import asyncio
import json
import logging
import os
from pathlib import Path
import secrets
import time

from gateway.database import log_message
from gateway.messages.cs import build_cs_message, reply_content
from gateway.messages.cs_models import CSConfig, default_cs_config
from neonize.proto.Neonize_pb2 import JID
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message

settings: dict[str, tuple[CSConfig, str]] = {}
conversations: OrderedDict[tuple[str, str, str], dict] = OrderedDict()
seen_messages: OrderedDict[tuple[str, str, str], float] = OrderedDict()
inflight: set[tuple[str, str, str]] = set()
MAX_CACHE = 5000


def remember_message(key, timestamp):
    if key[2]:
        seen_messages[key] = timestamp
        while len(seen_messages) > MAX_CACHE:
            seen_messages.popitem(last=False)


def get_cs_settings(username: str) -> tuple[CSConfig, str]:
    if username not in settings:
        path = Path("storage") / username / "config" / "customer_service.json"
        try:
            saved = json.loads(path.read_text())
            settings[username] = (CSConfig.model_validate(saved["config"]), saved["revision"])
        except FileNotFoundError:
            settings[username] = (default_cs_config(), "default")
        except (OSError, ValueError, KeyError, TypeError):
            logging.getLogger(__name__).exception("Cannot load CS settings for %s; bot disabled", username)
            settings[username] = (default_cs_config(), "default")
    return settings[username]


def save_cs_settings(username: str, config: CSConfig) -> str:
    revision = secrets.token_hex(6)
    path = Path("storage") / username / "config" / "customer_service.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as target:
        json.dump({"config": config.model_dump(), "revision": revision}, target, ensure_ascii=False, indent=2)
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)
    settings[username] = (config, revision)
    for key in list(conversations):
        if key[0] == username:
            conversations.pop(key, None)
    return revision


def selected_input(message) -> str:
    """Read canonical IDs from all supported reply-message protobuf types."""
    raw = getattr(message, "_real_msg", None)
    if raw is not None:
        if raw.HasField("interactiveResponseMessage"):
            try:
                data = json.loads(raw.interactiveResponseMessage.nativeFlowResponseMessage.paramsJSON)
                if isinstance(data, dict):
                    for key in ("id", "selected_row_id", "selectedRowID", "response_id"):
                        if isinstance(data.get(key), str):
                            return data[key].strip()
            except (ValueError, TypeError):
                return ""
            return ""
        if raw.HasField("buttonsResponseMessage"):
            return raw.buttonsResponseMessage.selectedButtonID.strip()
        if raw.HasField("templateButtonReplyMessage"):
            return raw.templateButtonReplyMessage.selectedID.strip()
        if raw.HasField("listResponseMessage"):
            return raw.listResponseMessage.singleSelectReply.selectedRowID.strip()
    return str(getattr(message, "text", "") or "").strip()


def navigate(config: CSConfig, revision: str, value: str, current_node: str | None):
    nodes = {node.id: node for node in config.nodes}
    current = nodes.get(current_node, nodes[config.root_node])
    if value.casefold() in config.keywords or value.casefold() in ("0", "kembali", "menu"):
        return nodes[config.root_node], False
    if value.startswith("cs:"):
        parts = value.split(":")
        if len(parts) == 4 and parts[1] == revision and parts[2] == current.id:
            for option in current.options:
                if parts[3] == option.id:
                    return nodes[option.target], False
        return nodes[config.root_node], True  # Old/stale buttons never execute another flow.
    if value.isascii() and value.isdigit() and 1 <= int(value) <= len(current.options):
        return nodes[current.options[int(value) - 1].target], False
    for option in current.options:
        if value.casefold() in (option.label.casefold(), option.id.casefold()):
            return nodes[option.target], False
    return current, bool(current_node)


def active_conversations(username: str) -> list[dict]:
    now = time.monotonic()
    for key, state in list(conversations.items()):
        if now >= state["expires_at"] and not state.get("idle_at"):
            conversations.pop(key, None)
    return [{"phone": key[1], "chat": key[2], "node": state["node"],
             "paused": state["paused_until"] > now,
             "idle_remaining": max(0, int(state.get("idle_at", now) - now)) if state.get("idle_at") else None,
             "pause_remaining": max(0, int(state["paused_until"] - now))}
            for key, state in reversed(conversations.items()) if key[0] == username]


async def close_idle_conversations(get_client):
    """Send one closing message without requiring another incoming event."""
    limit = asyncio.Semaphore(5)
    async def close(key, state):
        async with limit:
            now = time.monotonic()
            if conversations.get(key) is not state or key in inflight or not state.get("idle_at") or now < state["idle_at"]:
                return
            config, revision = get_cs_settings(key[0])
            if not config.enabled or revision != state["revision"]:
                conversations.pop(key, None)
                return
            client, _ = get_client(key[0], key[1])
            # Remove first: a closing notification is attempted once, even on failure.
            conversations.pop(key, None)
            if not client:
                logging.getLogger(__name__).warning("CS idle session closed offline: %s", key)
                return
            try:
                user, server = key[2].rsplit("@", 1)
                text = config.closing_message.replace("{business}", config.business_name)
                await asyncio.wait_for(client.send_message(JID(User=user, Server=server), Message(conversation=text)), timeout=10)
                await log_message(key[0], f"DEVICE({key[1]})", key[2], f"[CS CLOSED] {text}", "OUTGOING")
            except Exception:
                logging.getLogger(__name__).exception("CS closing notification failed: %s", key)
    await asyncio.gather(*(close(key, state) for key, state in list(conversations.items())
                           if state.get("idle_at") and time.monotonic() >= state["idle_at"]))


async def inactivity_worker(get_client):
    while True:
        await asyncio.sleep(1)
        try:
            await close_idle_conversations(get_client)
        except Exception:
            logging.getLogger(__name__).exception("CS inactivity worker failed")


async def try_customer_service(client, username: str, phone: str, message) -> bool:
    config, revision = get_cs_settings(username)
    if not config.enabled or (config.devices and phone not in config.devices):
        return False
    if getattr(message, "from_me", False) or getattr(message, "is_edit", False):
        return False
    chat = getattr(message, "chat", None)
    if getattr(chat, "Server", "") not in ("s.whatsapp.net", "lid"):
        return False
    value = selected_input(message)
    chat_id = f"{chat.User}@{chat.Server}"
    key = (username, phone, chat_id)
    now = time.monotonic()
    active_conversations(username)
    state = conversations.get(key)
    if state and state["revision"] != revision:
        state = None
    if state and state["paused_until"] and now >= state["paused_until"]:
        state = None
    if state and state.get("idle_at") and now >= state["idle_at"]:
        conversations.pop(key, None)
        state = None
    if not value and not state:
        return False
    reset = value.casefold() in config.keywords or value.casefold() in ("menu", "0", "kembali")
    if not state and not config.start_on_first_message and not reset and not value.startswith("cs:"):
        return False
    if key in inflight:
        return True
    message_id = str(getattr(getattr(message, "info", None), "ID", ""))
    seen_key = (username, phone, message_id)
    if message_id and seen_key in seen_messages:
        return True
    if state and state.get("idle_at"):
        state["idle_at"] = now + config.inactivity_minutes * 60
    if not value:
        remember_message(seen_key, now)
        return True
    if state and state["paused_until"] > now and not reset:
        remember_message(seen_key, now)
        return True  # Claim paused chats so AI Rich/ping cannot reply over the human handoff.
    if state and now - state["last_sent"] < config.cooldown_seconds:
        remember_message(seen_key, now)
        return True
    inflight.add(key)
    try:
        node, invalid = navigate(config, revision, value if state or not value.startswith("cs:") else "cs:expired", state["node"] if state else None)
        content = reply_content(config, node, getattr(message, "pushname", "") or "Pelanggan", revision)
        if invalid:
            content["body"] = "Pilihan tidak dikenali atau tombol sudah kedaluwarsa. Pilih kembali dari menu ini.\n\n" + content["body"]
        reply = await build_cs_message(content, client)
        await client.send_message(chat, reply)
        sent_at = time.monotonic()
        pause = config.handoff_minutes * 60 if node.handoff else 0
        conversations[key] = {"node": node.id, "revision": revision, "last_sent": sent_at,
                              "paused_until": sent_at + pause if pause else 0,
                              "idle_at": 0 if pause else sent_at + config.inactivity_minutes * 60,
                              "expires_at": sent_at + max(config.session_ttl_minutes * 60, pause)}
        conversations.move_to_end(key)
        remember_message(seen_key, sent_at)
        while len(conversations) > MAX_CACHE:
            conversations.popitem(last=False)
        await log_message(username, chat_id, f"DEVICE({phone})", f"[CS IN] {value}", "INCOMING")
        await log_message(username, f"DEVICE({phone})", chat_id, f"[CS {node.id}] {content['body']}", "OUTGOING")
        return True
    finally:
        inflight.discard(key)
