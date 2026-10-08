import os
import unittest
from unittest.mock import AsyncMock, patch

import main
from neonize.aioze.events import ConnectFailureEv, KeepAliveRestoredEv, KeepAliveTimeoutEv
from neonize.proto.Neonize_pb2 import JID, Message, MessageInfo, MessageSource
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import ContextInfo, Message as WAMessage

from gateway.messages.store import store
import gateway.routes.newsletters as newsletters_api
import gateway.security as security
import gateway.services.auto_reply as auto_reply
import gateway.state as gateway_state
import gateway.whatsapp.clients as wa_clients
from gateway.whatsapp.serialization import Mess, QuotedMess


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pairing_returns_code_without_redirecting_process_output(self):
        import asyncio
        client = AsyncMock()
        client.connect_task = None
        client._pairing_ready = asyncio.Event()
        client._pairing_ready.set()
        client.PairPhone.return_value = 'ABCD-EFGH'
        self.assertEqual(await wa_clients.get_pairing_code_safe(client, '+628123456789'), 'ABCD-EFGH')
        client.connect.assert_awaited_once()
        client.PairPhone.assert_awaited_once_with('628123456789', show_push_notification=True)

    async def test_pairing_surfaces_connection_task_failure_without_waiting_for_timeout(self):
        import asyncio
        from types import SimpleNamespace
        client = SimpleNamespace(_pairing_ready=asyncio.Event(), connect_task=None)
        async def connect():
            async def fail():
                raise RuntimeError('socket closed')
            client.connect_task = asyncio.create_task(fail())
        client.connect = connect
        with self.assertRaisesRegex(RuntimeError, 'socket closed'):
            await wa_clients.get_pairing_code_safe(client, '+628123456789')

    async def test_pairing_surfaces_login_timeout_event_without_waiting_for_qr_timeout(self):
        import asyncio
        from types import SimpleNamespace
        client = SimpleNamespace(
            _pairing_ready=asyncio.Event(),
            _pairing_failed=asyncio.Event(),
            _pairing_failure_reason='Login event: timeout',
            connect_task=None,
        )
        async def connect():
            client.connect_task = asyncio.create_task(asyncio.sleep(30))
            asyncio.get_running_loop().call_soon(client._pairing_failed.set)
        client.connect = connect
        with self.assertRaisesRegex(RuntimeError, 'Login event: timeout'):
            await wa_clients.get_pairing_code_safe(client, '+628123456789')
        client.connect_task.cancel()

    async def test_airich_auto_reply_matches_and_applies_per_chat_cooldown(self):
        from types import SimpleNamespace
        username = 'auto-reply-test'
        old_rules = gateway_state.airich_auto_rules.get(username)
        gateway_state.airich_auto_rules[username] = [{
            'id': 'price', 'enabled': True, 'keyword': 'harga', 'match': 'contains',
            'scope': 'group', 'cooldown_seconds': 60,
            'blocks': [{'type': 'text', 'text': 'Silakan lihat katalog kami.'}],
        }]
        client = AsyncMock()
        chat = JID(User='120363000000001', Server='g.us')
        message = SimpleNamespace(
            text='Berapa harga paket?', is_edit=False, chat=chat,
            info=SimpleNamespace(ID='auto-reply-message-1'),
        )
        try:
            with patch.object(auto_reply, 'build_airich_message', new=AsyncMock(return_value='rich')) as build, \
                 patch.object(auto_reply, 'log_message', new=AsyncMock()):
                self.assertTrue(await auto_reply.try_airich_auto_reply(client, username, '628123456789', message))
                self.assertEqual(await auto_reply.try_airich_auto_reply(client, username, '628123456789', message), False)
                client.send_message.assert_awaited_once_with(chat, 'rich')
                build.assert_awaited_once()
        finally:
            gateway_state.airich_auto_rules.pop(username, None)
            if old_rules is not None:
                gateway_state.airich_auto_rules[username] = old_rules
            gateway_state.airich_auto_seen.pop(f'{username}:628123456789:auto-reply-message-1', None)
            gateway_state.airich_auto_last.pop((f'{username}:628123456789', '120363000000001@g.us', 'price'), None)

    async def test_failed_pairing_cleanup_removes_client_and_stops_worker(self):
        session_id = 'cleanup-test:628123456789'
        client = AsyncMock()
        gateway_state.clients[session_id] = client
        gateway_state.bot_status[session_id] = False
        try:
            await wa_clients.discard_failed_pairing_client(session_id, client)
            self.assertNotIn(session_id, gateway_state.clients)
            client.stop.assert_awaited_once()
        finally:
            gateway_state.clients.pop(session_id, None)
            gateway_state.bot_status.pop(session_id, None)

    async def test_incoming_text_and_quoted_reply(self):
        sender = JID(User='628123456789', Server='s.whatsapp.net')
        event = Message(Info=MessageInfo(ID='migration-test', MessageSource=MessageSource(Sender=sender, Chat=sender)), Message=WAMessage(conversation='ping'))
        client = AsyncMock()
        self.assertEqual(Mess(client, event).text, 'ping')
        store.add_message(event)
        try:
            quoted = QuotedMess(client, ContextInfo(participant='628123456789@s.whatsapp.net', stanzaID=event.Info.ID, quotedMessage=event.Message), sender)
            await quoted.reply('pong')
            client.reply_message.assert_awaited_once_with('pong', event)
        finally:
            store.messages.pop(event.Info.ID, None)

    async def test_timeout_keeps_session_and_client(self):
        class FakeClient:
            def __init__(self, path):
                self.handlers = {}
            def event(self, event):
                def register(fn):
                    self.handlers[event] = fn
                    return fn
                return register
            def qr(self, fn):
                return fn
        sid = 'migration-test:628123456789'
        with patch.object(wa_clients, 'NewAClient', FakeClient), patch.object(os, 'remove') as remove:
            wa_clients.start_neonize('migration-test', '628123456789', auto_connect=False)
            client = gateway_state.clients[sid]
            try:
                await client.handlers[ConnectFailureEv](client, 'temporary failure')
                await client.handlers[KeepAliveTimeoutEv](client, 'timeout')
                self.assertIs(gateway_state.clients[sid], client)
                remove.assert_not_called()
                await client.handlers[KeepAliveRestoredEv](client, None)
                self.assertTrue(gateway_state.bot_status[sid])
            finally:
                gateway_state.clients.pop(sid, None)
                gateway_state.bot_status.pop(sid, None)

    async def test_newsletter_without_picture(self):
        from neonize.proto.Neonize_pb2 import NewsletterMetadata
        client = AsyncMock()
        client.create_newsletter.return_value = NewsletterMetadata()
        with patch.object(newsletters_api, 'get_client', return_value=(client, '628123456789')):
            result = await newsletters_api.api_newsletter_create('Channel', username='migration-test')
        self.assertTrue(result['success'])
        client.create_newsletter.assert_awaited_once_with('Channel', '', b'')

    async def test_api_schema_and_passwords(self):
        self.assertIn('/api/resend', main.app.openapi()['paths'])
        hashed = security.hash_password('migration-password')
        self.assertTrue(security.verify_password('migration-password', hashed))
        self.assertFalse(security.verify_password('incorrect', hashed))
