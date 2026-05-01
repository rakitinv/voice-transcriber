"""
Pub/sub для частичных транскриптов: in-memory (один процесс) или Redis (несколько инстансов).

Redis: `VT_TRANSCRIPT_REDIS=1` и доступный `VT_REDIS_URL` / configs `redis.url`.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Protocol, runtime_checkable

from core.config import app_config
from core.logging import logger

_MAX_QUEUE = 64


@runtime_checkable
class TranscriptHub(Protocol):
    async def publish(self, conversation_id: str, payload: dict[str, Any]) -> None: ...

    async def subscribe(self, conversation_id: str) -> asyncio.Queue: ...

    async def unsubscribe(self, conversation_id: str, queue: asyncio.Queue) -> None: ...


class MemoryTranscriptHub:
    """Подписчики — asyncio.Queue на conversation_id."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = {}

    async def subscribe(self, conversation_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._subs.setdefault(conversation_id, []).append(q)
        return q

    async def unsubscribe(self, conversation_id: str, queue: asyncio.Queue) -> None:
        lst = self._subs.get(conversation_id)
        if not lst:
            return
        try:
            lst.remove(queue)
        except ValueError:
            return
        if not lst:
            del self._subs[conversation_id]

    async def publish(self, conversation_id: str, payload: dict[str, Any]) -> None:
        for q in list(self._subs.get(conversation_id, [])):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(
                    "Transcript hub queue full for conversation %s — dropping push",
                    conversation_id,
                )


_hub: TranscriptHub | None = None


def get_transcript_hub() -> TranscriptHub:
    global _hub
    if _hub is None:
        _hub = _create_transcript_hub()
    return _hub


def _create_transcript_hub() -> TranscriptHub:
    use_redis = os.environ.get("VT_TRANSCRIPT_REDIS", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if use_redis:
        from .ws_hub_redis import RedisTranscriptHub

        return RedisTranscriptHub(app_config.redis.url)
    return MemoryTranscriptHub()
