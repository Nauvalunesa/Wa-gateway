import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
from neonize.proto.Neonize_pb2 import JID

from gateway.routes.neonize_tools import SPRSend, send_spr
from gateway.services.neonize_spr import SPRUnavailableError, send_spr_group


class NeonizeSPRTests(unittest.IsolatedAsyncioTestCase):
    def test_installed_neonize_has_python_and_native_spr_apis(self):
        from neonize.aioze.client import NewAClient, gocode

        self.assertTrue(callable(getattr(NewAClient, "send_spr_group", None)))
        self.assertTrue(callable(getattr(gocode, "SendSPRMessage", None)))

    async def test_calls_only_the_dedicated_spr_transport(self):
        client = SimpleNamespace(
            send_spr_group=AsyncMock(return_value={"id": "spr-1"}),
            send_message=AsyncMock(),
        )

        result = await send_spr_group(
            client,
            "120363000000000000@g.us",
            ["628123456789@s.whatsapp.net"],
            "Pesan A untuk target",
            "Pesan B untuk anggota lain",
        )

        self.assertEqual(result, {"id": "spr-1"})
        client.send_spr_group.assert_awaited_once_with(
            "120363000000000000@g.us",
            ["628123456789@s.whatsapp.net"],
            "Pesan A untuk target",
            "Pesan B untuk anggota lain",
        )
        client.send_message.assert_not_awaited()

    async def test_missing_transport_fails_closed_without_sending_a_regular_message(self):
        client = SimpleNamespace(send_message=AsyncMock())

        with self.assertRaises(SPRUnavailableError):
            await send_spr_group(
                client,
                "120363000000000000@g.us",
                ["628123456789@s.whatsapp.net"],
                "Pesan A",
                "Pesan B",
            )

        client.send_message.assert_not_awaited()

    async def test_route_reports_missing_neonize_transport_as_not_implemented(self):
        client = SimpleNamespace(send_message=AsyncMock())
        data = SPRSend(
            phone="628123456789",
            group_jid="120363000000000000@g.us",
            target_jids=["628123456789@s.whatsapp.net"],
            target_message="Pesan A",
            decoy_message="Pesan B",
        )

        # Keep the route isolated from WhatsApp state and assert it never falls
        # back to send_message when the installed Neonize build lacks SPR.
        from unittest.mock import patch

        with patch("gateway.routes.neonize_tools.get_client", return_value=(client, data.phone)):
            with self.assertRaises(HTTPException) as raised:
                await send_spr(data, username="tester")

        self.assertEqual(raised.exception.status_code, 501)
        client.send_message.assert_not_awaited()

    async def test_route_checks_membership_and_uses_spr_transport(self):
        group_jid = JID(User="120363000000000000", Server="g.us")
        target_jid = JID(User="628123456789", Server="s.whatsapp.net")
        member = SimpleNamespace(JID=target_jid, LID=JID(), PhoneNumber=target_jid)
        group_info = SimpleNamespace(Participants=[member], GroupName=SimpleNamespace(Name="Testing"))
        client = SimpleNamespace(
            send_spr_group=AsyncMock(return_value={"id": "spr-2"}),
            send_message=AsyncMock(),
            get_group_info=AsyncMock(return_value=group_info),
            get_pn_from_lid=AsyncMock(),
        )
        data = SPRSend(
            phone="628123456789",
            group_jid="120363000000000000@g.us",
            target_jids=["628123456789@s.whatsapp.net"],
            target_message="Pesan A",
            decoy_message="Pesan B",
        )

        from unittest.mock import patch

        with (
            patch("gateway.routes.neonize_tools.get_client", return_value=(client, data.phone)),
            patch("gateway.routes.neonize_tools.get_actual_jid", AsyncMock(return_value=group_jid)),
            patch("gateway.routes.neonize_tools.log_message", AsyncMock()),
        ):
            result = await send_spr(data, username="tester")

        self.assertTrue(result["success"])
        self.assertEqual(result["target_count"], 1)
        client.send_spr_group.assert_awaited_once_with(
            "120363000000000000@g.us",
            ["628123456789@s.whatsapp.net"],
            "Pesan A",
            "Pesan B",
        )
        client.send_message.assert_not_awaited()

    async def test_route_rejects_a_target_outside_the_selected_group(self):
        group_jid = JID(User="120363000000000000", Server="g.us")
        member_jid = JID(User="628111111111", Server="s.whatsapp.net")
        client = SimpleNamespace(
            send_spr_group=AsyncMock(),
            send_message=AsyncMock(),
            get_group_info=AsyncMock(return_value=SimpleNamespace(
                Participants=[SimpleNamespace(JID=member_jid, LID=JID(), PhoneNumber=member_jid)],
                GroupName=SimpleNamespace(Name="Testing"),
            )),
            get_pn_from_lid=AsyncMock(),
        )
        data = SPRSend(
            phone="628123456789",
            group_jid="120363000000000000@g.us",
            target_jids=["628123456789@s.whatsapp.net"],
            target_message="Pesan A",
            decoy_message="Pesan B",
        )

        from unittest.mock import patch

        with (
            patch("gateway.routes.neonize_tools.get_client", return_value=(client, data.phone)),
            patch("gateway.routes.neonize_tools.get_actual_jid", AsyncMock(return_value=group_jid)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await send_spr(data, username="tester")

        self.assertEqual(raised.exception.status_code, 422)
        client.send_spr_group.assert_not_awaited()
        client.send_message.assert_not_awaited()

    async def test_rejects_private_chat_destinations_and_bad_targets(self):
        client = SimpleNamespace(send_spr_group=AsyncMock())

        with self.assertRaises(ValueError):
            await send_spr_group(client, "628123456789@s.whatsapp.net", ["628123456789@s.whatsapp.net"], "A", "B")
        with self.assertRaises(ValueError):
            await send_spr_group(client, "120363000000000000@g.us", ["120363000000000000@g.us"], "A", "B")

        client.send_spr_group.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
