"""Adapter for Neonize's optional group SPR transport.

SPR needs selective group sender-key distribution and a retry hook. A normal
``send_message`` call cannot provide those semantics, so this adapter fails
closed unless the installed Neonize client exposes ``send_spr_group``.
"""

from __future__ import annotations

import inspect
from typing import Any, Iterable


MAX_SPR_TARGETS = 25
SPR_METHOD = "send_spr_group"


class SPRUnavailableError(RuntimeError):
    """Raised when the active Neonize build has no group SPR transport."""


def _validate_group_jid(value: str) -> str:
    jid = str(value).strip()
    if not jid.endswith("@g.us") or not jid.split("@", 1)[0]:
        raise ValueError("Tujuan SPR harus berupa grup WhatsApp (@g.us).")
    return jid


def _validate_targets(values: Iterable[str]) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for raw in values:
        jid = str(raw).strip()
        server = jid.rsplit("@", 1)[-1] if "@" in jid else ""
        if server not in {"s.whatsapp.net", "lid"} or not jid.rsplit("@", 1)[0]:
            raise ValueError("Target SPR harus anggota pribadi grup (@s.whatsapp.net atau @lid).")
        if jid not in seen:
            targets.append(jid)
            seen.add(jid)
    if not targets:
        raise ValueError("Pilih setidaknya satu target SPR dari daftar anggota grup.")
    if len(targets) > MAX_SPR_TARGETS:
        raise ValueError(f"Maksimal {MAX_SPR_TARGETS} target SPR per pengiriman.")
    return targets


def spr_capability(client: Any) -> dict[str, Any]:
    supported = callable(getattr(client, SPR_METHOD, None))
    return {
        "supported": supported,
        "method": SPR_METHOD,
        "reason": "" if supported else (
            "Versi Neonize yang sedang terpasang belum menyediakan transport SPR grup "
            "(distribusi sender key selektif dan penggantian retry decoy). Pengiriman dinonaktifkan; "
            "pesan tidak akan dialihkan menjadi DM atau pesan grup biasa."
        ),
    }


async def send_spr_group(
    client: Any,
    group_jid: str,
    target_jids: Iterable[str],
    target_message: str,
    decoy_message: str,
) -> Any:
    """Send target/decoy branches through Neonize's dedicated SPR transport.

    The expected client API is ``send_spr_group(group_jid, target_jids, A, B)``.
    No normal send API is used as a fallback because it would expose A to the
    entire group.
    """
    group = _validate_group_jid(group_jid)
    targets = _validate_targets(target_jids)
    target_text = str(target_message).strip()
    decoy_text = str(decoy_message).strip()
    if not target_text:
        raise ValueError("Pesan A untuk target tidak boleh kosong.")
    if not decoy_text:
        raise ValueError("Pesan B untuk anggota lain tidak boleh kosong.")

    method = getattr(client, SPR_METHOD, None)
    if not callable(method):
        raise SPRUnavailableError(spr_capability(client)["reason"])

    result = method(group, targets, target_text, decoy_text)
    if inspect.isawaitable(result):
        result = await result
    return result
