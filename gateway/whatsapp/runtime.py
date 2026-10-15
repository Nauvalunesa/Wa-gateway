"""Keep long-lived Neonize connections out of asyncio's shared worker pool."""

import asyncio
import secrets
import threading

from neonize.aioze.client import GoCode, NewAClient, gocode


async def native_thread_call(function, *args, poll_interval=0.05):
    finished = threading.Event()
    outcome = []

    def run():
        try:
            outcome.append((True, function(*args)))
        except BaseException as exc:
            outcome.append((False, exc))
        finally:
            finished.set()

    threading.Thread(target=run, name="neonize-native", daemon=True).start()
    while not finished.is_set():
        await asyncio.sleep(poll_interval)
    succeeded, value = outcome[0]
    if succeeded:
        return value
    raise value


class ConnectionGoCode(GoCode):
    def __init__(self, native=gocode):
        self.native = native

    async def Neonize(self, *args):
        # This FFI call lives for the entire WhatsApp session. One session must
        # not consume a shared worker needed by PairPhone or other API calls.
        return await native_thread_call(self.native.Neonize, *args, poll_interval=0.5)

    async def Stop(self, *args):
        # Cleanup must work even when unrelated shared workers are busy.
        return await native_thread_call(self.native.Stop, *args)

    async def Disconnect(self, *args):
        return await native_thread_call(self.native.Disconnect, *args)

    async def SendSPRMessage(self, *args):
        # SPR uses a blocking native FFI call that must not wait behind other
        # default-executor jobs while this long-lived WhatsApp connection runs.
        return await native_thread_call(self.native.SendSPRMessage, *args)


class GatewayClient(NewAClient):
    def __init__(self, name):
        # The database path stays stable, but each worker gets a fresh identity.
        # A callback/Stop from an old worker cannot target its replacement.
        super().__init__(name, uuid=secrets.token_hex(16))
        # Neonize 0.5.2 keeps its FFI adapter in this private attribute. Limit the
        # compatibility hook to this module rather than modifying site-packages.
        self._NewAClient__client = ConnectionGoCode()
