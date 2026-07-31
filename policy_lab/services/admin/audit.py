"""Append-only, hash-chained audit records with deterministic verification."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping


GENESIS_HASH = "0" * 64


def _canonical(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    event_id: str
    timestamp: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    payload_json: str
    previous_hash: str
    event_hash: str

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)


class HashChainedAuditLog:
    def __init__(self) -> None:
        self._events: tuple[AuditEvent, ...] = ()

    def append(
        self,
        *,
        event_id: str,
        timestamp: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        if any(event.event_id == event_id for event in self._events):
            raise ValueError(f"duplicate audit event_id: {event_id}")
        sequence = len(self._events) + 1
        previous_hash = self._events[-1].event_hash if self._events else GENESIS_HASH
        payload_json = _canonical(dict(payload or {}))
        body = {
            "sequence": sequence,
            "event_id": event_id,
            "timestamp": timestamp,
            "actor_id": actor_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "payload_json": payload_json,
            "previous_hash": previous_hash,
        }
        event_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        event = AuditEvent(event_hash=event_hash, **body)
        self._events = (*self._events, event)
        return event

    def events(self) -> tuple[AuditEvent, ...]:
        return self._events

    def verify(self, events: tuple[AuditEvent, ...] | None = None) -> bool:
        previous_hash = GENESIS_HASH
        selected = self._events if events is None else events
        for expected_sequence, event in enumerate(selected, start=1):
            body = {
                "sequence": event.sequence,
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "actor_id": event.actor_id,
                "action": event.action,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "payload_json": event.payload_json,
                "previous_hash": event.previous_hash,
            }
            calculated = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
            if (
                event.sequence != expected_sequence
                or event.previous_hash != previous_hash
                or event.event_hash != calculated
            ):
                return False
            previous_hash = event.event_hash
        return True
