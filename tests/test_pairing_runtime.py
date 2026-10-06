import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import main
from neonize_runtime import ConnectionGoCode


class PairingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Keep a periodic loop tick in the test harness, including environments
        # where worker-thread socketpair wakeups are restricted by a sandbox.
        async def tick():
            while True:
                await asyncio.sleep(.01)
        self.tick = asyncio.create_task(tick())

    async def asyncTearDown(self):
        self.tick.cancel()
        await asyncio.gather(self.tick, return_exceptions=True)

    async def test_live_connections_leave_shared_worker_available(self):
        # The old runtime consumes this single shared worker with its first
        # connection, so PairPhone/Stop queue forever behind that connection.
        executor = ThreadPoolExecutor(max_workers=1)
        previous_executor = asyncio.get_running_loop()._default_executor
        asyncio.get_running_loop().set_default_executor(executor)
        started = [Event() for _ in range(3)]
        stopped = [Event() for _ in range(3)]

        def connect(index):
            started[index].set()
            if not stopped[index].wait(5):
                raise RuntimeError('test connection did not stop')
            return b''

        def stop(index):
            stopped[index].set()

        adapter = ConnectionGoCode(SimpleNamespace(Neonize=connect, Stop=stop))
        connections = [asyncio.create_task(adapter.Neonize(i)) for i in range(3)]
        try:
            async with asyncio.timeout(2):
                while not all(event.is_set() for event in started):
                    await asyncio.sleep(.01)
                self.assertEqual(await asyncio.to_thread(lambda: 'pairing available'), 'pairing available')
                await asyncio.gather(*(adapter.Stop(i) for i in range(3)))
                await asyncio.gather(*connections)
        finally:
            for event in stopped:
                event.set()
            await asyncio.gather(*connections, return_exceptions=True)
            executor.shutdown(wait=True)
            asyncio.get_running_loop()._default_executor = previous_executor

    async def test_stop_works_even_when_shared_worker_is_busy(self):
        executor = ThreadPoolExecutor(max_workers=1)
        previous_executor = asyncio.get_running_loop()._default_executor
        asyncio.get_running_loop().set_default_executor(executor)
        busy = Event()
        release = Event()
        def block():
            busy.set()
            release.wait(5)
        blocker = asyncio.create_task(asyncio.to_thread(block))
        stop = Event()
        adapter = ConnectionGoCode(SimpleNamespace(Stop=lambda _: stop.set()))
        try:
            async with asyncio.timeout(2):
                while not busy.is_set():
                    await asyncio.sleep(.01)
                await adapter.Stop(b'client')
                self.assertTrue(stop.is_set())
        finally:
            release.set()
            await blocker
            executor.shutdown(wait=True)
            asyncio.get_running_loop()._default_executor = previous_executor

    async def test_failed_pairing_can_retry_without_process_restart(self):
        sid = 'pairing-test:628123456789'
        attempts = []
        def start(user, phone, auto_connect):
            client = AsyncMock()
            client.connect_task = None
            attempts.append(client)
            main.clients[sid] = client
            main.bot_status[sid] = False
        tasks_before = set(main.client_cleanup_tasks)
        try:
            with patch.object(main, 'init_user_db', AsyncMock()), \
                 patch.object(main, 'start_neonize', start), \
                 patch.object(main.os.path, 'exists', return_value=False), \
                 patch.object(main.os, 'makedirs'), \
                 patch.object(main, 'get_pairing_code_safe', AsyncMock(side_effect=[RuntimeError('PairPhone timeout'), 'ABCD-EFGH'])):
                with self.assertRaises(main.HTTPException):
                    await main.request_pairing_code('pairing-test', '628123456789')
                self.assertNotIn(sid, main.clients)
                self.assertNotIn(sid, main.pairing_sessions)
                attempts[0].stop.assert_awaited_once()
                result = await main.request_pairing_code('pairing-test', '628123456789')
                self.assertEqual(result['code'], 'ABCD-EFGH')
                self.assertIs(main.clients[sid], attempts[1])
                with self.assertRaises(main.HTTPException) as conflict:
                    await main.request_pairing_code('pairing-test', '628123456789')
                self.assertEqual(conflict.exception.status_code, 409)
        finally:
            cleanup = list(main.client_cleanup_tasks - tasks_before)
            for task in cleanup:
                task.cancel()
            await asyncio.gather(*cleanup, return_exceptions=True)
            main.clients.pop(sid, None)
            main.bot_status.pop(sid, None)
            main.pairing_sessions.discard(sid)

    async def test_old_client_callbacks_cannot_mark_replacement_offline(self):
        class FakeClient:
            def __init__(self, path):
                self.handlers = {}
            def event(self, event):
                def register(handler):
                    self.handlers[event] = handler
                    return handler
                return register
            def qr(self, handler):
                return handler
        sid = 'old-client-test:628123456789'
        try:
            with patch.object(main, 'NewAClient', FakeClient):
                main.start_neonize('old-client-test', '628123456789', auto_connect=False)
            old = main.clients[sid]
            replacement = object()
            main.clients[sid] = replacement
            main.bot_status[sid] = True
            await old.handlers[main.DisconnectedEv](old, None)
            await old.handlers[main.ConnectFailureEv](old, 'old timeout')
            self.assertIs(main.clients[sid], replacement)
            self.assertTrue(main.bot_status[sid])
        finally:
            main.clients.pop(sid, None)
            main.bot_status.pop(sid, None)
