import json
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from google.protobuf.json_format import ParseDict, ParseError
from neonize.proto.Neonize_pb2 import JID

import main


class InteractiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_and_post_accept_canonical_and_legacy_buttons(self):
        actions = [
            ("quick_reply", {"display_text": "Bantuan", "id": ".help"}),
            ("cta_url", {"display_text": "Website", "url": "https://example.com"}),
            ("cta_call", {"display_text": "Telepon", "phone_number": "628123456789"}),
            ("cta_copy", {"display_text": "Salin", "copy_code": "PROMO"}),
            ("single_select", {"title": "Menu", "sections": [{"title": "Layanan", "rows": [{"title": "Top Up", "id": "1"}]}]}),
        ]
        client = AsyncMock()
        jid = JID(User="628123456789", Server="s.whatsapp.net")
        for spelling in ["buttonParamsJson", "buttonParamsJSON"]:
            payload = {
                "body": {"text": "Silakan pilih"},
                "footer": {"text": "Utusan"},
                "nativeFlowMessage": {"buttons": [{"name": name, spelling: json.dumps(params)} for name, params in actions]},
            }
            before = deepcopy(payload)
            for method in ["get", "post"]:
                with self.subTest(spelling=spelling, method=method), \
                     patch.object(main, "get_client", return_value=(client, "device")), \
                     patch.object(main, "get_actual_jid", AsyncMock(return_value=jid)), \
                     patch.object(main, "get_mentions_list", AsyncMock(return_value=[])), \
                     patch.object(main, "log_message", AsyncMock()):
                    if method == "get":
                        response = await main.api_send_interactive_get(None, "628123456789", json.dumps(payload), username="test")
                    else:
                        data = main.InteractivePayload(to="628123456789", payload=payload)
                        response = await main.api_send_interactive_post(None, data, username="test")
                        self.assertEqual(data.payload, before)
                    self.assertTrue(response["success"])
                    sent = client.send_message.await_args.args[1]
                    wire = main.WAMessage.FromString(sent.SerializeToString())
                    buttons = wire.interactiveMessage.nativeFlowMessage.buttons
                    self.assertEqual(len(buttons), len(actions))
                    for button, (name, params) in zip(buttons, actions):
                        self.assertEqual(button.name, name)
                        self.assertEqual(json.loads(button.buttonParamsJSON), params)

    async def test_canonical_value_wins_when_both_spellings_present(self):
        payload = {"nativeFlowMessage": {"buttons": [{"name": "quick_reply", "buttonParamsJSON": '{"id":"new"}', "buttonParamsJson": '{"id":"old"}'}]}}
        normalized = main.normalize_interactive_payload(payload)
        message = ParseDict(normalized, main.InteractiveMessage())
        self.assertEqual(message.nativeFlowMessage.buttons[0].buttonParamsJSON, '{"id":"new"}')
        self.assertIn("buttonParamsJson", payload["nativeFlowMessage"]["buttons"][0])

    async def test_unknown_button_fields_are_still_rejected(self):
        payload = {"nativeFlowMessage": {"buttons": [{"name": "quick_reply", "buttonParamsJson": "{}", "invalidField": True}]}}
        with self.assertRaises(ParseError):
            ParseDict(main.normalize_interactive_payload(payload), main.InteractiveMessage())
