import unittest

from gateway.services.neonize_tools import build_ad_message
from gateway.routes.neonize_tools import AdSend


class InteractiveAdTests(unittest.TestCase):
    def test_ad_request_does_not_require_message_text(self):
        request = AdSend(
            phone="639752530262",
            to="628123456789",
            title="Utusan",
            advertiser="Utusan.chat",
            source_url="https://utusan.chat",
            source_app="Utusan.chat",
            button_label="Kunjungi website",
        )

        self.assertFalse(hasattr(request, "text"))

    def test_ad_message_contains_card_and_cta_with_empty_interactive_envelope(self):
        message = build_ad_message(
            title="Utusan",
            advertiser="Utusan.chat",
            image_url="",
            source_url="https://utusan.chat",
            source_app="Utusan.chat",
            button_label="Kunjungi website",
        )

        interactive = message.interactiveMessage
        self.assertTrue(interactive.HasField("header"))
        self.assertTrue(interactive.HasField("body"))
        self.assertEqual(interactive.body.text, "")
        self.assertTrue(interactive.HasField("footer"))
        self.assertEqual(interactive.footer.text, "")
        self.assertTrue(interactive.contextInfo.HasField("externalAdReply"))
        ad = interactive.contextInfo.externalAdReply
        self.assertEqual(ad.title, "Utusan")
        self.assertEqual(ad.body, "Utusan.chat")
        self.assertEqual(ad.greetingMessageBody, "")
        self.assertFalse(ad.containsAutoReply)
        self.assertEqual(len(interactive.nativeFlowMessage.buttons), 1)
        self.assertEqual(interactive.nativeFlowMessage.buttons[0].name, "cta_url")


if __name__ == "__main__":
    unittest.main()
