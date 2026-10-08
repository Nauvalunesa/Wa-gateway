"""Background broadcast execution and personalization."""
import asyncio

from gateway.database import log_message
from gateway.state import bot_status, clients
from gateway.whatsapp.addressing import get_target_jid


async def run_blast(username: str, phone_list: list, message_template: str, delay_min: int, delay_max: int, device_phones: list):
    import random
    import re

    print(f"🚀 Starting Blast for {username} to {len(phone_list)} numbers...")

    for i, item in enumerate(phone_list):
        # Rotate devices
        device_phone = device_phones[i % len(device_phones)]
        session_id = f"{username}:{device_phone}"
        client = clients.get(session_id)

        if not client or not bot_status.get(session_id):
            print(f"❌ Device {device_phone} disconnected, skipping one target.")
            continue

        target = str(item.get('phone', '')).strip()
        if not target: continue

        # Personalization
        final_msg = message_template
        for key, value in item.items():
            final_msg = final_msg.replace(f"{{{key}}}", str(value))

        target_jid = get_target_jid(target)
        try:
            await client.send_message(target_jid, final_msg)
            await log_message(username, f"DEVICE({device_phone})", target, final_msg, "OUTGOING")
        except Exception as e:
            print(f"❌ Failed to send blast to {target}: {e}")

        # Delay except for the last one
        if i < len(phone_list) - 1:
            wait_time = random.randint(delay_min, delay_max)
            await asyncio.sleep(wait_time)

    print(f"✅ Blast Campaign for {username} finished!")
