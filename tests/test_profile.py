import base64
from io import BytesIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from neonize.proto.Neonize_pb2 import Device, JID, ProfilePictureInfo, PrivacySettings, UserInfo, GetUserInfoSingleReturnFunction
from neonize.utils.enum import PrivacySetting, PrivacySettingType, ReceiptType
from PIL import Image

from gateway.application import create_app
from gateway.messages.profile_models import ProfilePreferences
from gateway.services.profile import MAX_PHOTO_BYTES, prepare_profile_photo
from gateway.services import profile_privacy
from gateway.state import bot_status, clients


def photo(width=240, height=600):
    out = BytesIO()
    Image.new("RGB", (width, height), "green").save(out, "PNG")
    return out.getvalue()


class PhotoPreparationTests(unittest.TestCase):
    def test_square_modes_and_original_preserve_actual_jpeg_geometry(self):
        original = prepare_profile_photo(photo(), "original")
        self.assertEqual((original["width"], original["height"]), (240, 600))
        self.assertTrue(original["experimental"])
        for mode in ["cover", "contain"]:
            result = prepare_profile_photo(photo(), mode)
            image = Image.open(BytesIO(result["bytes"]))
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (640, 640))
            self.assertEqual(base64.b64decode(result["preview"].split(",")[1]), result["bytes"])
            if mode == "contain": self.assertEqual(image.getpixel((1, 1)), (255, 255, 255))

    def test_orientation_transparency_and_invalid_files(self):
        out = BytesIO(); exif = Image.Exif(); exif[274] = 6
        Image.new("RGB", (100, 200), "red").save(out, "JPEG", exif=exif)
        result = prepare_profile_photo(out.getvalue(), "original")
        self.assertEqual(result["source_size"], [200, 100])
        out = BytesIO(); Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(out, "PNG")
        result = prepare_profile_photo(out.getvalue(), "contain", "#000000")
        self.assertEqual(Image.open(BytesIO(result["bytes"])).getpixel((1, 1)), (0, 0, 0))
        for data, mode, background, status in [
            (b"not image", "contain", "#ffffff", 422),
            (b"x" * (MAX_PHOTO_BYTES+1), "cover", "#ffffff", 413),
            (photo(), "missing", "#ffffff", 422),
            (photo(), "contain", "invalid", 422),
        ]:
            with self.assertRaises(HTTPException) as context: prepare_profile_photo(data, mode, background)
            self.assertEqual(context.exception.status_code, status)


class ProfileAPITests(unittest.TestCase):
    def setUp(self):
        self.original = os.getcwd(); self.directory = tempfile.TemporaryDirectory(prefix="utusan-profile-")
        os.chdir(self.directory.name)
        self.http = TestClient(create_app(), base_url="https://testserver"); self.http.__enter__()
        self.http.post("/api/web/register", json={"username": "profileowner", "password": "Testing-password"})
        self.phone = "628123456789"; self.sid = f"profileowner:{self.phone}"
        self.client = AsyncMock()
        jid = JID(User=self.phone, Server="s.whatsapp.net")
        self.client.get_me.return_value = Device(JID=jid, PushName="CS Toko")
        self.client.get_user_info.return_value = [GetUserInfoSingleReturnFunction(JID=jid, UserInfo=UserInfo(Status="Siap membantu"))]
        self.client.get_profile_picture.return_value = ProfilePictureInfo(URL="https://example.com/profile.jpg")
        self.client.get_privacy_settings.return_value = PrivacySettings(ReadReceipts=2, LastSeen=3, Online=5, Profile=3, GroupAdd=3, CallAdd=6)
        self.client.set_profile_photo.return_value = "photo-id"
        clients[self.sid] = self.client; bot_status[self.sid] = True

    def tearDown(self):
        clients.pop(self.sid, None); bot_status.pop(self.sid, None)
        self.http.__exit__(None, None, None)
        os.chdir(self.original); self.directory.cleanup(); profile_privacy.preferences.clear()

    def test_read_name_about_and_partial_read_failures(self):
        result = self.http.get("/api/web/wa-profile", params={"phone": self.phone})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["name"], "CS Toko"); self.assertEqual(result.json()["about"], "Siap membantu")
        self.assertEqual(self.http.put("/api/web/wa-profile/name", json={"phone": self.phone, "name": "CS Baru"}).status_code, 200)
        self.client.set_profile_name.assert_awaited_once_with("CS Baru")
        self.assertEqual(self.http.put("/api/web/wa-profile/about", json={"phone": self.phone, "about": "Buka 09.00"}).status_code, 200)
        self.client.set_status_message.assert_awaited_once_with("Buka 09.00")
        self.client.get_user_info.side_effect = RuntimeError("temporary")
        result = self.http.get("/api/web/wa-profile", params={"phone": self.phone}).json()
        self.assertIsNone(result["about"]); self.assertTrue(result["warnings"])

    def test_photo_preview_and_sent_bytes_are_identical_and_stale_preview_rejected(self):
        data = photo()
        preview = self.http.post("/api/web/wa-profile/photo/preview", files={"file": ("photo.png", data, "image/png")}, data={"mode": "original"}).json()
        self.assertFalse(preview["sent"]); self.client.set_profile_photo.assert_not_called()
        body = {"phone": self.phone, "mode": "original", "sha256": preview["sha256"]}
        result = self.http.post("/api/web/wa-profile/photo", files={"file": ("photo.png", data, "image/png")}, data=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["picture_id"], "photo-id")
        self.assertEqual(self.client.set_profile_photo.await_args.args[0], base64.b64decode(preview["preview"].split(",")[1]))
        body["mode"] = "cover"
        self.assertEqual(self.http.post("/api/web/wa-profile/photo", files={"file": ("photo.png", data)}, data=body).status_code, 409)
        self.assertEqual(self.client.set_profile_photo.await_count, 1)

    def test_privacy_and_preferences_use_supported_enums_and_persist(self):
        result = self.http.get("/api/web/wa-profile/privacy", params={"phone": self.phone}).json()
        self.assertEqual(result["privacy"]["read_receipts"], "all")
        result = self.http.put("/api/web/wa-profile/privacy", json={"phone": self.phone, "setting": "read_receipts", "value": "none"})
        self.assertEqual(result.status_code, 200)
        self.client.set_privacy_setting.assert_awaited_once_with(PrivacySettingType.READ_RECEIPTS, PrivacySetting.NONE)
        self.assertEqual(self.http.put("/api/web/wa-profile/privacy", json={"phone": self.phone, "setting": "read_receipts", "value": "contacts"}).status_code, 422)
        self.assertEqual(self.http.put("/api/web/wa-profile/preferences", json={"phone": self.phone, "auto_read": True, "auto_read_scope": "private"}).status_code, 200)
        profile_privacy.preferences.clear()
        self.assertTrue(profile_privacy.get_preferences("profileowner", self.phone).auto_read)
        self.assertTrue(Path(f"storage/profileowner/config/profile_{self.phone}.json").exists())

    def test_cookie_origin_account_isolation_validation_and_offline_safety(self):
        for bad_name in [" ", "x"*26]:
            self.assertEqual(self.http.put("/api/web/wa-profile/name", json={"phone": self.phone, "name": bad_name}).status_code, 422)
        self.assertEqual(self.http.put("/api/web/wa-profile/name", json={"phone": "", "name": "CS"}).status_code, 422)
        self.assertEqual(self.http.put("/api/web/wa-profile/name", json={"phone": self.phone, "name": "CS"}, headers={"Origin": "https://other.test"}).status_code, 403)
        self.client.set_profile_name.side_effect = RuntimeError("rejected")
        self.assertEqual(self.http.put("/api/web/wa-profile/name", json={"phone": self.phone, "name": "CS"}).status_code, 502)
        self.client.set_profile_name.reset_mock()
        self.http.post("/api/web/logout")
        self.assertEqual(self.http.get("/api/web/wa-profile", params={"phone": self.phone}).status_code, 401)
        self.http.post("/api/web/register", json={"username": "profileother", "password": "Testing-password"})
        self.assertEqual(self.http.put("/api/web/wa-profile/name", json={"phone": self.phone, "name": "CS"}).status_code, 503)
        self.client.set_profile_name.assert_not_awaited()


class AutoReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncMock(); profile_privacy.preferences.clear()
        profile_privacy.preferences[("owner", "628123456789")] = ProfilePreferences(auto_read=True)

    async def asyncTearDown(self):
        profile_privacy.preferences.clear()

    def message(self, server="s.whatsapp.net"):
        return SimpleNamespace(chat=JID(User="628222222222", Server=server), sender=JID(User="628222222222", Server="s.whatsapp.net"), info=SimpleNamespace(ID="message"), from_me=False, is_edit=False)

    async def test_auto_read_uses_live_privacy_read_receipt_and_scopes(self):
        message = self.message()
        await profile_privacy.auto_read_message(self.client, "owner", "628123456789", message)
        self.client.mark_read.assert_awaited_once_with("message", chat=message.chat, sender=message.sender, receipt=ReceiptType.READ)
        await profile_privacy.auto_read_message(self.client, "owner", "628123456789", self.message("g.us"))
        self.assertEqual(self.client.mark_read.await_count, 1)
        profile_privacy.preferences[("owner", "628123456789")].auto_read_scope = "all"
        await profile_privacy.auto_read_message(self.client, "owner", "628123456789", self.message("g.us"))
        self.assertEqual(self.client.mark_read.await_count, 2)
        for server in ["newsletter", "broadcast"]:
            await profile_privacy.auto_read_message(self.client, "owner", "628123456789", self.message(server))
        self.assertEqual(self.client.mark_read.await_count, 2)

    async def test_outgoing_edits_and_failed_read_do_not_break_reply_handling(self):
        for flag in ["from_me", "is_edit"]:
            message = self.message(); setattr(message, flag, True)
            await profile_privacy.auto_read_message(self.client, "owner", "628123456789", message)
        self.client.mark_read.assert_not_awaited()
        self.client.mark_read.side_effect = RuntimeError("offline")
        await profile_privacy.auto_read_message(self.client, "owner", "628123456789", self.message())
