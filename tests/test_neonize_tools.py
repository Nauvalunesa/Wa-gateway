import unittest
from pydantic import ValidationError

from gateway.services.neonize_tools import build_ad_message
from gateway.routes.neonize_tools import AdSend


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
        self.assertEqual(ad.greetingMessageBody, "Diskon akhir pekan")
        self.assertTrue(ad.containsAutoReply)
        self.assertTrue(ad.automatedGreetingMessageShown)
        self.assertEqual(ad.thumbnail, b"small-jpeg-thumbnail")
        self.assertEqual(ad.sourceURL, "https://utusan.chat")


if __name__ == "__main__":
    unittest.main()
