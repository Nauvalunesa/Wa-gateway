import time
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from gateway.application import create_app

from neonize.aioze.events import MessageEv
from neonize.proto.Neonize_pb2 import JID

from gateway.services import ping
from gateway.state import clients, bot_status
from gateway.whatsapp import clients as wa


class PingTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_metrics_and_duration_without_network_ping_claim(self):
        def read(path):
            return {'/proc/cpuinfo': 'model name : Example CPU\n', '/proc/meminfo': 'MemTotal: 2097152 kB\nMemAvailable: 1048576 kB\n', '/proc/uptime': '90061 0'}.get(path, '')
        with patch.object(ping, '_read', side_effect=read), patch.object(ping.os, 'getloadavg', return_value=(1, 2, 3)), patch.object(ping.shutil, 'disk_usage', return_value=SimpleNamespace(used=ping.GIB, total=2*ping.GIB)), patch.object(ping.time, 'perf_counter', return_value=10.125):
            result = await ping.build_ping_reply(10)
        self.assertIn('pong!', result)
        self.assertIn('125.00 ms', result)
        self.assertIn('CPU: Example CPU', result)
        self.assertIn('RAM server: 1.00 / 2.00 GiB', result)
        self.assertIn('Disk aplikasi: 1.00 / 2.00 GiB', result)
        self.assertIn('Uptime server: 1 hari 01:01:01', result)
        self.assertIn('sebelum pengiriman WhatsApp', result)
        with patch.object(ping, '_read', return_value=''), patch.object(ping.shutil, 'disk_usage', side_effect=OSError), patch.object(ping.os, 'getloadavg', side_effect=OSError):
            fallback = await ping.build_ping_reply(time.perf_counter())
        self.assertIn('Tidak tersedia', fallback)

    async def test_ping_event_reply_and_existing_auto_reply_priority(self):
        class Client:
            def __init__(self, path): self.handlers = {}
            def event(self, event):
                def register(handler): self.handlers[event] = handler; return handler
                return register
            def qr(self, handler): return handler
        sid = 'ping-test:628111111111'
        jid = JID(User='628222222222', Server='s.whatsapp.net')
        message = SimpleNamespace(sender=jid, chat=jid, text=' PING ', from_me=False, is_edit=False, is_media=False, reply=AsyncMock())
        try:
            with patch.object(wa, 'NewAClient', Client), patch.object(wa.ms, 'add_message'), patch.object(wa, 'Mess', return_value=message), patch.object(wa, 'auto_read_message', AsyncMock()), patch.object(wa, 'try_customer_service', AsyncMock(return_value=False)) as cs, patch.object(wa, 'try_airich_auto_reply', AsyncMock(return_value=False)), patch.object(wa, 'ping_enabled', return_value=True) as enabled, patch.object(wa, 'build_ping_reply', AsyncMock(return_value='pong! 12.00 ms')) as build:
                wa.start_neonize('ping-test', '628111111111', auto_connect=False)
                client = clients[sid]
                await client.handlers[MessageEv](client, object())
                message.reply.assert_awaited_once_with('pong! 12.00 ms')
                self.assertIsInstance(build.await_args.args[0], float)
                cs.return_value = True
                await client.handlers[MessageEv](client, object())
                self.assertEqual(message.reply.await_count, 1)
                cs.return_value = False; enabled.return_value = False
                await client.handlers[MessageEv](client, object())
                self.assertEqual(message.reply.await_count, 1)
                self.assertEqual(build.await_count, 1)
                enabled.return_value = True
                cs.return_value = False; message.is_edit = True
                await client.handlers[MessageEv](client, object())
                self.assertEqual(message.reply.await_count, 1)
        finally:
            clients.pop(sid, None); bot_status.pop(sid, None)


class PingSettingsTests(unittest.TestCase):
    def test_cookie_security_account_isolation_and_restart_persistence(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory(prefix='utusan-ping-') as directory:
            try:
                os.chdir(directory); ping.preferences.clear()
                with TestClient(create_app(), base_url='https://testserver') as http:
                    self.assertEqual(http.get('/api/web/ping-settings').status_code, 401)
                    http.post('/api/web/register', json={'username': 'pingowner', 'password': 'Testing-password'})
                    self.assertTrue(http.get('/api/web/ping-settings').json()['enabled'])
                    self.assertEqual(http.put('/api/web/ping-settings', json={'enabled': False}, headers={'Origin': 'https://other.test'}).status_code, 403)
                    self.assertEqual(http.put('/api/web/ping-settings', json={'enabled': 'false'}).status_code, 422)
                    self.assertEqual(http.put('/api/web/ping-settings', json={'enabled': False}).status_code, 200)
                    ping.preferences.clear()
                    self.assertFalse(http.get('/api/web/ping-settings').json()['enabled'])
                    http.post('/api/web/logout')
                    http.post('/api/web/register', json={'username': 'pingother', 'password': 'Testing-password'})
                    self.assertTrue(http.get('/api/web/ping-settings').json()['enabled'])
                    self.assertFalse(ping.ping_enabled('pingowner'))
            finally:
                os.chdir(original); ping.preferences.clear()
