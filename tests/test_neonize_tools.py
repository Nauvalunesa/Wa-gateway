import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError

from gateway.services.neonize_tools import build_ad_message
from gateway.routes.neonize_tools import AdSend, send_ad


class InteractiveAdTests(unittest.TestCase):
    def test_ad_request_requires_message_text(self):
        request = AdSend(
            phone="639752530262",
            to="628123456789",
            text="Diskon akhir pekan",
            title="Utusan",
            advertiser="Utusan.chat",
            source_url="https://utusan.chat",
            source_app="Utusan.chat",
        )

        self.assertEqual(request.text, "Diskon akhir pekan")
        with self.assertRaises(ValidationError):
            AdSend(
                phone="639752530262",
                to="628123456789",
                title="Utusan",
                advertiser="Utusan.chat",
                source_url="https://utusan.chat",
                source_app="Utusan.chat",
            )

    def test_ad_message_is_one_ad_bubble_with_caption_and_thumbnail(self):
        message = build_ad_message(
            text="Diskon akhir pekan",
            thumbnail=b"small-jpeg-thumbnail",
            title="Utusan",
            advertiser="Utusan.chat",
            image_url="",
            source_url="https://utusan.chat",
            source_app="Utusan.chat",
        )

        self.assertTrue(message.HasField("extendedTextMessage"))
        self.assertFalse(message.HasField("interactiveMessage"))
        extended = message.extendedTextMessage
        self.assertEqual(extended.text, "Diskon akhir pekan")
        self.assertTrue(extended.contextInfo.HasField("externalAdReply"))
        ad = extended.contextInfo.externalAdReply
        self.assertEqual(ad.title, "Utusan")
        self.assertEqual(ad.body, "Utusan.chat")
        self.assertFalse(ad.greetingMessageBody)
        self.assertFalse(ad.containsAutoReply)
        self.assertFalse(ad.automatedGreetingMessageShown)
        self.assertEqual(ad.thumbnail, b"small-jpeg-thumbnail")
        self.assertEqual(ad.sourceURL, "https://utusan.chat")


class ZInteractiveAdRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_ad_route_sends_only_one_whatsapp_message(self):
        client = SimpleNamespace(send_message=AsyncMock())
        target = SimpleNamespace(Server="s.whatsapp.net")
        request = AdSend(
            phone="639752530262",
            to="628123456789",
            text="Diskon akhir pekan",
            title="Utusan",
            advertiser="Utusan.chat",
            source_url="https://utusan.chat",
            source_app="Utusan.chat",
        )

        with (
            patch("gateway.routes.neonize_tools.get_client", return_value=(client, None)),
            patch("gateway.routes.neonize_tools.get_actual_jid", new=AsyncMock(return_value=target)),
            patch("gateway.routes.neonize_tools.download_ad_thumbnail", return_value=None),
            patch("gateway.routes.neonize_tools.log_message", new=AsyncMock()),
        ):
            result = await send_ad(request, username="test-account")

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Satu pesan iklan dikirim.")
        client.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
