import json
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

    def test_ad_message_is_one_interactive_ad_with_recipient_triggered_greeting(self):
        message = build_ad_message(
            text="Diskon akhir pekan",
            thumbnail=b"small-jpeg-thumbnail",
            title="Utusan",
            advertiser="Utusan.chat",
            image_url="",
            source_url="https://utusan.chat",
            source_app="Utusan.chat",
        )

        self.assertTrue(message.HasField("interactiveMessage"))
        self.assertFalse(message.HasField("extendedTextMessage"))
        interactive = message.interactiveMessage
        self.assertEqual(interactive.body.text, "Diskon akhir pekan")
        self.assertTrue(interactive.contextInfo.HasField("externalAdReply"))
        ad = interactive.contextInfo.externalAdReply
        self.assertEqual(ad.title, "Utusan")
        self.assertEqual(ad.body, "Utusan.chat")
        self.assertEqual(ad.greetingMessageBody, "Diskon akhir pekan")
        self.assertTrue(ad.containsAutoReply)
        self.assertTrue(ad.automatedGreetingMessageShown)
        self.assertEqual(ad.thumbnail, b"small-jpeg-thumbnail")
        self.assertEqual(ad.sourceURL, "https://utusan.chat")
        self.assertEqual(interactive.footer.text, "Utusan.chat")
        self.assertEqual(len(interactive.nativeFlowMessage.buttons), 1)
        button = interactive.nativeFlowMessage.buttons[0]
        self.assertEqual(button.name, "cta_url")
        self.assertEqual(json.loads(button.buttonParamsJSON), {
            "display_text": "🌐 Kunjungi Web",
            "url": "https://utusan.chat",
            "merchant_url": "https://utusan.chat",
        })


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
            button_text="Buka situs",
            source_url="https://utusan.chat",
            source_app="Utusan.chat",
        )

        with (
            patch("gateway.routes.neonize_tools.get_client", return_value=(client, None)),
            patch("gateway.routes.neonize_tools.get_actual_jid", new=AsyncMock(return_value=target)),
            patch("gateway.routes.neonize_tools.asyncio.to_thread", new=AsyncMock(return_value=None)),
            patch("gateway.routes.neonize_tools.log_message", new=AsyncMock()),
        ):
            result = await send_ad(request, username="test-account")

        self.assertTrue(result["success"])
        client.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
