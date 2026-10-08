"""Keep long-lived Neonize connections out of asyncio's shared worker pool."""

import asyncio
import secrets
import threading

from neonize.aioze.client import GoCode, NewAClient, gocode


async def native_thread_call(function, *args):
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    def complete(value, error):
        if result.done():
            return
        if error is None:
            result.set_result(value)
        else:
            result.set_exception(error)

    def run():
        try:
            value, error = function(*args), None
        except Exception as exc:
            value, error = None, exc
        try:
            loop.call_soon_threadsafe(complete, value, error)
        except RuntimeError:
            pass  # The loop has already closed during process shutdown.

    threading.Thread(target=run, name="neonize-native", daemon=True).start()
    return await result


class ConnectionGoCode(GoCode):
    def __init__(self, native=gocode):
        self.native = native

    async def Neonize(self, *args):
        # This FFI call lives for the entire WhatsApp session. One session must
        # not consume a shared worker needed by PairPhone or other API calls.
        return await native_thread_call(self.native.Neonize, *args)

    async def Stop(self, *args):
        # Cleanup must work even when unrelated shared workers are busy.
        return await native_thread_call(self.native.Stop, *args)

    async def Disconnect(self, *args):
        return await native_thread_call(self.native.Disconnect, *args)


class GatewayClient(NewAClient):
    def __init__(self, name):
        # The database path stays stable, but each worker gets a fresh identity.
        # A callback/Stop from an old worker cannot target its replacement.
        super().__init__(name, uuid=secrets.token_hex(16))
        # Neonize 0.5.2 keeps its FFI adapter in this private attribute. Limit the
        # compatibility hook to this module rather than modifying site-packages.
        self._NewAClient__client = ConnectionGoCode()
