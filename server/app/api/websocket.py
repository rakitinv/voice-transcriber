"""
WebSocket endpoints for realtime audio streaming and transcription.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from core.config import app_config
from core.db import get_db
from core.logging import logger
from core.s3 import storage
from plugins.loader import plugin_registry
from workers.tasks.asr import transcribe_chunk
from ..models import Conversation, User
from .dependencies import get_current_user

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, conversation_id: str):
        """Accept a WebSocket connection."""
        await websocket.accept()
        self.active_connections[conversation_id] = websocket
        logger.info(f"WebSocket connected for conversation {conversation_id}")

    def disconnect(self, conversation_id: str):
        """Remove a WebSocket connection."""
        if conversation_id in self.active_connections:
            del self.active_connections[conversation_id]
            logger.info(f"WebSocket disconnected for conversation {conversation_id}")

    async def send_transcript(self, conversation_id: str, text: str):
        """Send transcript text to client."""
        if conversation_id in self.active_connections:
            websocket = self.active_connections[conversation_id]
            try:
                await websocket.send_json({"type": "transcript", "text": text})
            except Exception as e:
                logger.error(f"Failed to send transcript to {conversation_id}: {e}")


manager = ConnectionManager()


@router.websocket("/ws/audio/{conversation_id}")
async def websocket_audio(
    websocket: WebSocket,
    conversation_id: UUID,
    token: str,
    db: Session = Depends(get_db),
):
    """
    WebSocket endpoint for receiving audio chunks.

    Client sends audio chunks (WebM + Opus), server processes and returns transcripts.
    """
    # TODO: Validate JWT token from query parameter
    # For now, this is a simplified version

    await manager.connect(websocket, str(conversation_id))

    try:
        # Verify conversation exists
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if conversation is None:
            await websocket.send_json({"type": "error", "message": "Conversation not found"})
            await websocket.close()
            return

        # Buffer for audio chunks
        audio_buffer = bytearray()
        chunk_size_ms = 1000  # 1 second chunks (configurable)

        while True:
            # Receive audio chunk
            data = await websocket.receive()
            if "bytes" in data:
                audio_data = data["bytes"]
                audio_buffer.extend(audio_data)

                # When buffer reaches chunk size, process it
                # This is simplified - in production, you'd use proper audio processing
                if len(audio_buffer) >= chunk_size_ms * 16:  # Rough estimate
                    # Process chunk
                    chunk_bytes = bytes(audio_buffer)
                    audio_buffer.clear()

                    # Queue transcription task
                    # For realtime, you might want to use transcribe_chunk directly
                    result = transcribe_chunk.delay(chunk_bytes, language=None)
                    transcript_text = result.get(timeout=5)  # Wait up to 5 seconds

                    # Send transcript back
                    await manager.send_transcript(str(conversation_id), transcript_text)

            elif "text" in data:
                # Handle text messages (e.g., control commands)
                message = json.loads(data["text"])
                if message.get("type") == "close":
                    break

    except WebSocketDisconnect:
        manager.disconnect(str(conversation_id))
    except Exception as e:
        logger.error(f"WebSocket error for {conversation_id}: {e}")
        manager.disconnect(str(conversation_id))


@router.websocket("/ws/transcript/{conversation_id}")
async def websocket_transcript(
    websocket: WebSocket,
    conversation_id: UUID,
):
    """
    WebSocket endpoint for receiving realtime transcripts.

    Server sends transcript updates as they become available.
    """
    await manager.connect(websocket, str(conversation_id))

    try:
        # Send initial connection message
        await websocket.send_json({"type": "connected", "conversation_id": str(conversation_id)})

        # Keep connection alive and send updates
        # In production, this would subscribe to a message queue (Redis pub/sub)
        while True:
            await asyncio.sleep(1)
            # Placeholder - would receive from message queue

    except WebSocketDisconnect:
        manager.disconnect(str(conversation_id))
    except Exception as e:
        logger.error(f"WebSocket transcript error for {conversation_id}: {e}")
        manager.disconnect(str(conversation_id))
