"""Shared in-memory device state and auto-reply caches."""
from typing import Any, Dict, List

from gateway.whatsapp.runtime import GatewayClient as NewAClient


clients: Dict[str, NewAClient] = {}


bot_status: Dict[str, bool] = {}


bot_numbers: Dict[str, str] = {}


pairing_sessions = set() # Track sessions that are currently pairing


client_cleanup_tasks = set()


airich_auto_rules: Dict[str, List[Dict[str, Any]]] = {}


airich_auto_seen: Dict[str, float] = {}


airich_auto_last: Dict[tuple[str, str, str], float] = {}
