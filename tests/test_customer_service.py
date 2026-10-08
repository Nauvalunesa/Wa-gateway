import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from neonize.proto.Neonize_pb2 import JID, Message as IncomingMessage, MessageInfo, MessageSource
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
from pydantic import ValidationError

from gateway.application import create_app
from gateway.messages.cs import build_cs_message, reply_content
from gateway.messages.cs_models import CSConfig, default_cs_config
from gateway.services import customer_service as cs
from gateway.state import clients, bot_status
from gateway.whatsapp import clients as wa_clients
from gateway.messages.store import store


class CustomerServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cs.settings.clear(); cs.conversations.clear(); cs.seen_messages.clear(); cs.inflight.clear()
        self.config = default_cs_config().model_copy(update={"enabled": True, "admin_phone": "628123456789", "cooldown_seconds": 0})
        cs.settings["tester"] = (self.config, "v1")
        self.client = AsyncMock()
        self.log = patch.object(cs, "log_message", AsyncMock())
        self.log.start()

    async def asyncTearDown(self):
        self.log.stop()
        cs.settings.clear(); cs.conversations.clear(); cs.seen_messages.clear(); cs.inflight.clear()

    def incoming(self, text="menu", mid="message-1", server="s.whatsapp.net", user="628222222222", raw=None):
        return SimpleNamespace(text=text, info=SimpleNamespace(ID=mid), chat=JID(User=user, Server=server),
                               pushname="Pelanggan", from_me=False, is_edit=False, _real_msg=raw)

    async def send(self, text, mid, phone="628111111111", **kwargs):
        return await cs.try_customer_service(self.client, "tester", phone, self.incoming(text, mid, **kwargs))

    def sent_node(self):
        message = self.client.send_message.await_args.args[1]
        return message.interactiveMessage.header.title

    async def test_clicked_buttons_send_nested_replies_and_return_to_menu(self):
        await self.send("menu", "a")
        self.assertEqual(self.sent_node(), "Selamat datang")
        wire = self.client.send_message.await_args.args[1]
        selected = json.loads(wire.interactiveMessage.nativeFlowMessage.buttons[1].buttonParamsJSON)["id"]
        raw = Message(interactiveResponseMessage={"nativeFlowResponseMessage": {"paramsJSON": json.dumps({"id": selected})}})
        await self.send("", "b", raw=raw)
        self.assertEqual(self.sent_node(), "Pusat bantuan")
        await self.send("cs:v1:faq:jam", "c")
        self.assertEqual(self.sent_node(), "Jam operasional")
        await self.send("cs:v1:jam:menu", "d")
        self.assertEqual(self.sent_node(), "Selamat datang")
        self.assertEqual(self.client.send_message.await_count, 4)

    async def test_numbers_and_labels_follow_current_submenu(self):
        await self.send("halo", "a")
        await self.send("2", "b")
        self.assertEqual(self.sent_node(), "Pusat bantuan")
        await self.send("Alamat & kontak", "c")
        self.assertEqual(self.sent_node(), "Alamat & kontak")
        await self.send("1", "d")
        self.assertEqual(self.sent_node(), "Selamat datang")

    async def test_all_four_reply_types_extract_selected_ids(self):
        variants = [
            Message(buttonsResponseMessage={"selectedButtonID": "cs:v1:menu:faq"}),
            Message(templateButtonReplyMessage={"selectedID": "cs:v1:menu:faq"}),
            Message(listResponseMessage={"singleSelectReply": {"selectedRowID": "cs:v1:menu:faq"}}),
            Message(interactiveResponseMessage={"nativeFlowResponseMessage": {"paramsJSON": '{"selected_row_id":"cs:v1:menu:faq"}'}}),
        ]
        for raw in variants:
            self.assertEqual(cs.selected_input(self.incoming("", raw=raw)), "cs:v1:menu:faq")
        malformed = Message(interactiveResponseMessage={"nativeFlowResponseMessage": {"paramsJSON": '[]'}})
        self.assertEqual(cs.selected_input(self.incoming("bad", raw=malformed)), "")

    async def test_handoff_pauses_all_auto_replies_and_menu_resumes(self):
        await self.send("menu", "a")
        await self.send("3", "b")
        self.assertEqual(self.sent_node(), "Hubungi admin")
        self.assertIn("https://wa.me/628123456789", self.client.send_message.await_args.args[1].interactiveMessage.body.text)
        self.assertTrue(await self.send("Pesan untuk admin", "c"))
        self.assertEqual(self.client.send_message.await_count, 2)
        self.assertTrue(cs.active_conversations("tester")[0]["paused"])
        await self.send("menu", "d")
        self.assertEqual(self.sent_node(), "Selamat datang")
        self.assertFalse(cs.active_conversations("tester")[0]["paused"])

    async def test_expired_session_and_stale_buttons_reset_without_wrong_action(self):
        await self.send("menu", "a")
        await self.send("2", "b")
        await self.send("cs:v1:menu:admin", "c")
        self.assertEqual(self.sent_node(), "Selamat datang")
        self.assertFalse(cs.active_conversations("tester")[0]["paused"])
        await self.send("cs:old:menu:admin", "d")
        self.assertEqual(self.sent_node(), "Selamat datang")
        key = next(iter(cs.conversations)); cs.conversations[key]["expires_at"] = 0
        await self.send("halo", "e")
        self.assertEqual(self.sent_node(), "Selamat datang")

    async def test_accounts_devices_chats_and_non_private_events_are_isolated(self):
        await self.send("menu", "a")
        await self.send("2", "b")
        await self.send("menu", "c", phone="628333333333")
        await self.send("menu", "d", user="628444444444")
        self.assertEqual(len(cs.active_conversations("tester")), 3)
        self.assertEqual(cs.active_conversations("other"), [])
        for server in ["g.us", "newsletter", "broadcast"]:
            self.assertFalse(await self.send("menu", f"x-{server}", server=server))
        for field in ["from_me", "is_edit"]:
            message = self.incoming(); setattr(message, field, True)
            self.assertFalse(await cs.try_customer_service(self.client, "tester", "628111111111", message))
        self.config.devices = ["628555555555"]
        self.assertFalse(await self.send("menu", "excluded"))

    async def test_duplicate_cooldown_and_failed_send_retry(self):
        await self.send("menu", "same")
        await self.send("menu", "same")
        self.assertEqual(self.client.send_message.await_count, 1)
        self.config.cooldown_seconds = 60
        await self.send("2", "fast")
        self.assertEqual(self.client.send_message.await_count, 1)
        self.config.cooldown_seconds = 0
        self.client.send_message.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError): await self.send("2", "retry")
        self.client.send_message.side_effect = None
        await self.send("2", "retry")
        self.assertEqual(self.sent_node(), "Pusat bantuan")

    async def test_inflight_events_do_not_send_duplicate_replies(self):
        started = asyncio.Event(); release = asyncio.Event()
        async def sending(*args): started.set(); await release.wait()
        self.client.send_message.side_effect = sending
        first = asyncio.create_task(self.send("menu", "a"))
        await started.wait()
        self.assertTrue(await self.send("menu", "a"))
        release.set(); await first
        self.assertEqual(self.client.send_message.await_count, 1)

    async def test_inactivity_closes_once_at_three_minutes_without_new_message(self):
        with patch.object(cs.time, "monotonic", return_value=100):
            await self.send("menu", "a")
        resolver = lambda *args: (self.client, args[1])
        with patch.object(cs.time, "monotonic", return_value=279):
            await cs.close_idle_conversations(resolver)
        self.assertEqual(self.client.send_message.await_count, 1)
        with patch.object(cs.time, "monotonic", return_value=280):
            await cs.close_idle_conversations(resolver)
            await cs.close_idle_conversations(resolver)
        self.assertEqual(self.client.send_message.await_count, 2)
        self.assertEqual(self.client.send_message.await_args.args[1].conversation, self.config.closing_message)
        self.assertFalse(cs.conversations)
        await self.send("cs:v1:menu:admin", "old")
        self.assertEqual(self.sent_node(), "Selamat datang")

    async def test_response_refreshes_timer_including_media_but_duplicates_do_not(self):
        with patch.object(cs.time, "monotonic", return_value=100):
            await self.send("menu", "a")
        key = next(iter(cs.conversations))
        with patch.object(cs.time, "monotonic", return_value=200):
            await self.send("menu", "a")
            self.assertEqual(cs.conversations[key]["idle_at"], 280)
            await self.send("", "media")
            self.assertEqual(cs.conversations[key]["idle_at"], 380)
        with patch.object(cs.time, "monotonic", return_value=250):
            await self.send("", "media")
            self.assertEqual(cs.conversations[key]["idle_at"], 380)
        with patch.object(cs.time, "monotonic", return_value=300):
            await cs.close_idle_conversations(lambda *args: (self.client, args[1]))
        self.assertEqual(self.client.send_message.await_count, 1)

    async def test_idle_closure_respects_handoff_disabled_and_offline_and_failure(self):
        await self.send("menu", "a")
        await self.send("3", "b")
        key = next(iter(cs.conversations))
        self.assertEqual(cs.conversations[key]["idle_at"], 0)
        resolver = lambda *args: (self.client, args[1])
        await cs.close_idle_conversations(resolver)
        self.assertEqual(self.client.send_message.await_count, 2)
        for mode in ['disabled', 'offline', 'failure']:
            self.config.enabled = True
            await self.send("menu", mode)
            cs.conversations[key]["idle_at"] = 1
            before = self.client.send_message.await_count
            if mode == 'disabled': self.config.enabled = False
            if mode == 'failure': self.client.send_message.side_effect = RuntimeError('offline')
            await cs.close_idle_conversations((lambda *args: (None, args[1])) if mode == 'offline' else resolver)
            await cs.close_idle_conversations(resolver)
            self.assertNotIn(key, cs.conversations)
            self.assertEqual(self.client.send_message.await_count, before + (1 if mode == 'failure' else 0))
            self.client.send_message.side_effect = None

    async def test_keyword_only_mode_and_disabled_bot_leave_other_rules_available(self):
        self.config.start_on_first_message = False
        self.assertFalse(await self.send("pesan lain", "a"))
        self.assertTrue(await self.send("menu", "b"))
        self.config.enabled = False
        self.assertFalse(await self.send("menu", "c"))

    async def test_all_send_formats_have_real_wire_messages(self):
        for mode, field in [("buttons", "interactiveMessage"), ("list", "interactiveMessage"), ("legacy", "buttonsMessage"), ("text", "conversation")]:
            config = default_cs_config(); config.reply_mode = mode
            message = await build_cs_message(reply_content(config, config.nodes[0], "Test", "v1"))
            wire = Message.FromString(message.SerializeToString())
            self.assertTrue(wire.HasField(field))

    async def test_real_message_event_dispatches_cs_before_airich_rules(self):
        class FakeClient:
            def __init__(self, path):
                self.handlers = {}
                self.send_message = AsyncMock()
            def event(self, event):
                def register(handler):
                    self.handlers[event] = handler
                    return handler
                return register
            def qr(self, handler):
                return handler
        from neonize.aioze.events import MessageEv
        phone = "628111111111"; sid = f"tester:{phone}"
        jid = JID(User="628222222222", Server="s.whatsapp.net")
        try:
            with patch.object(wa_clients, "NewAClient", FakeClient), patch.object(wa_clients, "try_airich_auto_reply", AsyncMock()) as airich:
                wa_clients.start_neonize("tester", phone, auto_connect=False)
                client = clients[sid]
                for mid, raw in [("cs-event-1", Message(conversation="menu")), ("cs-event-2", Message(buttonsResponseMessage={"selectedButtonID": "cs:v1:menu:faq"}))]:
                    event = IncomingMessage(Info=MessageInfo(ID=mid, Pushname="Test", MessageSource=MessageSource(Chat=jid, Sender=jid)), Message=raw)
                    await client.handlers[MessageEv](client, event)
                self.assertEqual(client.send_message.await_count, 2)
                self.assertEqual(client.send_message.await_args.args[1].interactiveMessage.header.title, "Pusat bantuan")
                airich.assert_not_awaited()
        finally:
            clients.pop(sid, None); bot_status.pop(sid, None)
            store.messages.pop("cs-event-1", None); store.messages.pop("cs-event-2", None)


class CSConfigTests(unittest.TestCase):
    def test_invalid_targets_ids_and_admin_are_rejected(self):
        value = default_cs_config().model_dump()
        for change in [{"enabled": True}, {"admin_phone": "not-number"}, {"root_node": "missing"}, {"keywords": [" "]}]:
            with self.assertRaises(ValidationError): CSConfig.model_validate({**value, **change})
        value["nodes"][0]["options"][0]["target"] = "missing"
        with self.assertRaises(ValidationError): CSConfig.model_validate(value)

    def test_settings_persist_and_reset_only_the_owning_account(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="utusan-cs-save-") as directory:
            try:
                os.chdir(directory)
                config = default_cs_config()
                cs.conversations[("owner", "phone", "chat")] = {}
                cs.conversations[("other", "phone", "chat")] = {}
                revision = cs.save_cs_settings("owner", config)
                self.assertNotIn(("owner", "phone", "chat"), cs.conversations)
                self.assertIn(("other", "phone", "chat"), cs.conversations)
                cs.settings.pop("owner")
                loaded, loaded_revision = cs.get_cs_settings("owner")
                self.assertEqual(loaded, config); self.assertEqual(loaded_revision, revision)
                self.assertTrue(Path("storage/owner/config/customer_service.json").exists())
            finally:
                os.chdir(original); cs.settings.clear(); cs.conversations.clear()

    def test_cookie_api_preview_save_and_account_isolation(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="utusan-cs-api-") as directory:
            try:
                os.chdir(directory)
                with TestClient(create_app(), base_url="https://testserver") as http:
                    self.assertEqual(http.get("/api/web/customer-service").status_code, 401)
                    http.post("/api/web/register", json={"username": "csowner", "password": "Testing-password"})
                    config = http.get("/api/web/customer-service").json()["config"]
                    config.update({"enabled": True, "admin_phone": "628123456789", "business_name": "CS Toko"})
                    self.assertEqual(http.put("/api/web/customer-service", json=config).status_code, 200)
                    result = http.post("/api/web/customer-service/preview", json={"config": config, "text": "cs:preview:menu:faq", "current_node": "menu"}).json()
                    self.assertFalse(result["sent"]); self.assertEqual(result["reply"]["node"], "faq")
                    self.assertEqual(http.put("/api/web/customer-service", json=config, headers={"origin": "https://other.test"}).status_code, 403)
                    http.post("/api/web/logout")
                    http.post("/api/web/register", json={"username": "csother", "password": "Testing-password"})
                    self.assertFalse(http.get("/api/web/customer-service").json()["config"]["enabled"])
            finally:
                os.chdir(original); cs.settings.clear(); cs.conversations.clear(); cs.seen_messages.clear()
