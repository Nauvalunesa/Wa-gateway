from fastapi import HTTPException
from pydantic import ValidationError
from unittest.mock import patch
import unittest

from gateway.routes.neonize_tools import AdSend, send_ad


class DisabledAdTriggerTests(unittest.TestCase):
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

class AdRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_greeting_only_route_does_not_send_anything(self):
        request = AdSend(
            phone="639752530262",
            to="628123456789",
            text="Diskon akhir pekan",
            title="Utusan",
            advertiser="Utusan.chat",
            source_url="https://utusan.chat",
            source_app="Utusan.chat",
        )

        with patch("gateway.routes.neonize_tools.get_client") as get_client:
            with self.assertRaises(HTTPException) as raised:
                await send_ad(request, username="test-account")

        self.assertEqual(raised.exception.status_code, 409)
        get_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
