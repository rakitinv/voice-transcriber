"""Redis pub/sub для частичных транскриптов (масштабирование API)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis

from core.logging import logger

_MAX_QUEUE = 64
_CHANNEL_PREFIX = "transcript:"


class RedisTranscriptHub:
    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._redis: aioredis.Redis | None = None
        self._redis_lock = asyncio.Lock()

    async def _client(self) -> aioredis.Redis:
        async with self._redis_lock:
            if self._redis is None:
                self._redis = aioredis.from_url(self._url, decode_responses=True)
            return self._redis

    async def publish(self, conversation_id: str, payload: dict[str, Any]) -> None:
        r = await self._client()
        channel = f"{_CHANNEL_PREFIX}{conversation_id}"
        await r.publish(channel, json.dumps(payload, ensure_ascii=False))

    async def subscribe(self, conversation_id: str) -> asyncio.Queue:
        r = await self._client()
        pubsub = r.pubsub()
        channel = f"{_CHANNEL_PREFIX}{conversation_id}"
        await pubsub.subscribe(channel)

        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)

        async def pump() -> None:
            try:
                async for msg in pubsub.listen():
                    if msg is None:
                        continue
                    if msg.get("type") != "message":
                        continue
                    data = msg.get("data")
                    if data is None:
                        continue
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning("Bad JSON on transcript channel %s", channel)
                        continue
                    try:
                        q.put_nowait(payload)
                    except asyncio.QueueFull:
                        logger.warning(
                            "Transcript redis queue full for %s — drop",
                            conversation_id,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("Transcript redis pump error: %s", e)

        task = asyncio.create_task(pump())
        setattr(q, "_transcript_pubsub", pubsub)
        setattr(q, "_transcript_task", task)
        return q

    async def unsubscribe(self, conversation_id: str, queue: asyncio.Queue) -> None:
        task: asyncio.Task | None = getattr(queue, "_transcript_task", None)
        pubsub = getattr(queue, "_transcript_pubsub", None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if pubsub:
            channel = f"{_CHANNEL_PREFIX}{conversation_id}"
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception as e:
                logger.debug("pubsub close: %s", e)
