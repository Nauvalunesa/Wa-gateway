import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from neonize.aioze.client import NewAClient
from neonize.proto.Neonize_pb2 import GroupInfo, JID, NewsletterMetadata

import main

logging.getLogger("httpx").setLevel(logging.WARNING)


class MessageAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="utusan-message-audit-")
        self.original_cwd = os.getcwd()
        os.chdir(self.directory.name)
        Path("storage").mkdir()
        self.http = TestClient(main.app, base_url="https://testserver")
        self.http.__enter__()
        response = self.http.post("/api/web/register", json={"username": "auditor", "password": "testing-password"})
        self.assertEqual(response.status_code, 200)
        self.key = response.json()["api_key"]
        self.phone = "628123456789"
        self.sid = "auditor:" + self.phone
        self.client = AsyncMock(spec=NewAClient)
        self.client.is_connected = True
        self.client.me = None
        self.client.build_image_message.return_value = main.WAMessage(imageMessage={"URL": "https://mmg.whatsapp.net/image", "mimetype": "image/jpeg"})
        self.client.build_video_message.return_value = main.WAMessage(videoMessage={"URL": "https://mmg.whatsapp.net/video", "mimetype": "video/mp4"})
        self.client.build_poll_vote_creation.return_value = main.WAMessage(pollCreationMessage={"name": "Jadwal", "options": [{"optionName": "Pagi"}, {"optionName": "Sore"}], "selectableOptionsCount": 1})
        self.client.build_reaction.return_value = main.WAMessage(reactionMessage={"text": "👍"})
        async def send_contact(*args):
            return await NewAClient.send_contact(self.client, *args)
        self.client.send_contact.side_effect = send_contact
        group = GroupInfo(JID=JID(User="120363000000001", Server="g.us"))
        group.GroupName.Name = "Grup audit"
        self.client.get_joined_groups.return_value = [group]
        channel = NewsletterMetadata(ID=JID(User="120363000000001", Server="newsletter"))
        channel.ThreadMeta.Name.Text = "Channel audit"
        self.client.get_newsletter_info_with_invite.return_value = channel
        self.client.get_newsletter_info.return_value = channel
        self.client.create_newsletter.return_value = channel
        self.client.get_newsletter_messages.return_value = []
        main.clients[self.sid] = self.client
        main.bot_status[self.sid] = True

    def tearDown(self):
        main.clients.pop(self.sid, None)
        main.bot_status.pop(self.sid, None)
        main.bot_numbers.pop(self.sid, None)
        self.http.__exit__(None, None, None)
        os.chdir(self.original_cwd)
        self.directory.cleanup()

    def send(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["success"], response.text)
        return response

    def test_cookie_auth_all_composer_message_types(self):
        common = {"to": "6281776348790", "phone": self.phone}
        for path, extra in [
            ("send-message", {"text": "Halo"}),
            ("send-message", {"text": "Halo mention", "mentions": "6281776348790"}),
            ("send-image", {"image_url": "https://example.com/image.jpg"}),
            ("send-image", {"image_url": "https://example.com/image.jpg", "mentions": "6281776348790"}),
            ("send-image", {"image_url": "https://example.com/image.jpg", "hd": "true"}),
            ("send-video", {"video_url": "https://example.com/video.mp4", "viewonce": "true"}),
            ("send-audio", {"audio_url": "https://example.com/audio.mp3", "ptt": "true"}),
            ("send-document", {"document_url": "https://example.com/file.pdf", "filename": "file.pdf"}),
            ("send-sticker", {"sticker_url": "https://example.com/sticker.webp"}),
            ("send-contact", {"contact_name": "Contoh", "contact_number": "08123456789"}),
        ]:
            with self.subTest(path=path, extra=extra):
                self.send("GET", "/api/" + path, params={**common, **extra})
        contact = self.client.send_message.await_args.args[1].contactMessage
        self.assertIn("waid=628123456789", contact.vcard)
        self.send("POST", "/api/send-location", json={**common, "latitude": -6.2, "longitude": 106.8})
        self.send("POST", "/api/send-poll", json={**common, "question": "Jadwal", "options": ["Pagi", "Sore"]})
        self.send("POST", "/api/send-reaction", json={**common, "message_id": "test-id", "reaction": "👍"})
        self.send("POST", "/api/send-buttonv2", json={**common, "body": "Pilih", "buttons": [{"display_text": "Ya", "button_id": "yes"}]})
        self.send("GET", "/api/send-buttonv2", params={**common, "body": "Pilih", "buttons": json.dumps([{"display_text": "Ya", "button_id": "yes"}])})
        self.send("POST", "/api/send-interactive", json={**common, "payload": {"body": {"text": "Pilih"}, "nativeFlowMessage": {"buttons": [{"name": "quick_reply", "buttonParamsJson": '{"id":"yes","display_text":"Ya"}'}]}}, "media_url": "https://example.com/image.jpg"})
        self.send("POST", "/api/send-airich", json={**common, "blocks": [{"type": "html", "html": "<button>Hello</button>", "text": "Hello"}]})

    def test_status_wire_and_group_validation(self):
        for kind in ["text", "image", "video"]:
            with self.subTest(kind=kind):
                params = {"phone": self.phone, "type": kind, "text": "Status", "url": "https://example.com/media"}
                self.send("GET", "/api/send-status", params=params)
                self.send("GET", "/api/send-group-status", params={**params, "to": "120363000000001@g.us"})
                wire = main.WAMessage.FromString(self.client.send_message.await_args.args[1].SerializeToString())
                inner = wire.groupStatusMessageV2.message
                self.assertTrue(inner.conversation if kind == "text" else inner.HasField(kind + "Message"))
        self.assertEqual(self.http.get("/api/send-group-status", params={"to": "6281776348790", "type": "text"}).status_code, 422)
        self.assertEqual(self.http.get("/api/send-status", params={"type": "invalid"}).status_code, 400)

    def test_group_channel_and_preview_cookie_auth(self):
        groups = self.send("GET", "/api/web/groups", params={"phone": self.phone}).json()
        self.assertEqual(groups["count"], 1)
        self.assertEqual(groups["groups"][0]["name"], "Grup audit")
        self.send("GET", "/api/groups", params={"phone": self.phone})
        self.send("GET", "/api/newsletter/info-by-invite", params={"key": "invite123", "phone": self.phone})
        self.client.get_newsletter_info_with_invite.assert_awaited_with("invite123")
        self.send("POST", "/api/newsletter/create", params={"name": "Channel", "phone": self.phone})
        self.send("POST", "/api/newsletter/send", params={"to": "120363000000001@newsletter", "type": "text", "text": "Halo", "phone": self.phone})
        for path in ["info", "messages"]:
            self.send("GET", "/api/newsletter/" + path, params={"jid": "120363000000001@newsletter", "phone": self.phone})
        self.assertEqual(self.http.post("/api/newsletter/send", params={"to": "6281776348790", "text": "Hello"}).status_code, 400)
        self.send("POST", "/api/airich/preview", json={"to": "preview", "blocks": [{"type": "text", "text": "Hello"}]})

    def test_validation_and_offline_responses_do_not_send(self):
        bad_requests = [
            ("POST", "/api/send-poll", {"json": {"to": "x", "question": "   ", "options": ["A", "B"]}}),
            ("POST", "/api/send-poll", {"json": {"to": "x", "question": "Pilih", "options": ["A", "A"]}}),
            ("POST", "/api/send-location", {"json": {"to": "x", "latitude": 100, "longitude": 0}}),
            ("POST", "/api/send-buttonv2", {"json": {"to": "x", "body": "Pilih", "buttons": []}}),
            ("POST", "/api/send-interactive", {"json": {"to": "x", "payload": {}}}),
            ("GET", "/api/send-interactive", {"params": {"to": "x", "payload": "[]"}}),
            ("GET", "/api/send-interactive", {"params": {"to": "x", "payload": "not json"}}),
            ("POST", "/api/send-interactive", {"json": {"to": "x", "payload": {"header": "invalid"}, "media_url": "https://example.com/image.jpg"}}),
            ("POST", "/api/send-interactive", {"json": {"to": "x", "payload": {"nativeFlowMessage": {"buttons": ["invalid"]}}}}),
            ("GET", "/api/send-buttonv2", {"params": {"to": "x", "body": "Pilih", "buttons": "not json"}}),
            ("GET", "/api/send-contact", {"params": {"to": "x", "contact_name": " ", "contact_number": "08123456789"}}),
            ("GET", "/api/send-contact", {"params": {"to": "x", "contact_name": "A", "contact_number": "abc"}}),
            ("POST", "/api/pair", {"data": {"phone": "../other"}}),
        ]
        for method, path, kwargs in bad_requests:
            with self.subTest(path=path, kwargs=kwargs):
                response = self.http.request(method, path, **kwargs)
                self.assertEqual(response.status_code, 422, response.text)
        self.client.send_message.assert_not_awaited()
        main.bot_status[self.sid] = False
        self.assertEqual(self.http.get("/api/send-message", params={"to": "x", "text": "Halo", "phone": self.phone}).status_code, 503)

    def test_cookie_origin_rejection_and_external_key_compatibility(self):
        self.assertEqual(self.http.get("/api/status").status_code, 200)
        self.assertEqual(self.http.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.http.get("/api/status", headers={"Origin": "https://other.example"}).status_code, 403)
        self.assertEqual(self.http.get("/api/status", headers={"x-api-key": "invalid"}).status_code, 403)
        self.http.post("/api/web/logout")
        self.assertEqual(self.http.get("/api/status").status_code, 401)
        self.assertEqual(self.http.get("/api/status", headers={"x-api-key": self.key}).status_code, 200)
        self.assertEqual(self.http.get("/api/status", params={"key": self.key}).status_code, 200)
