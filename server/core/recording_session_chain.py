"""
Ordering conversations for §7 recording_session_id chains (autoprolong).

Segments share recording_session_id; each continuation links backward via previous_conversation_id.
Head segment: conversation.id == recording_session_id (ТЗ §7.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID


class ConversationChainSegment(Protocol):
    id: UUID
    recording_session_id: UUID
    previous_conversation_id: UUID | None
    created_at: datetime


def ordered_chain_segments(conversations: list[ConversationChainSegment]) -> list[ConversationChainSegment]:
    """Oldest segment first (head … tail). Fallback: created_at when links are inconsistent."""
    if not conversations:
        return []
    rows = list(conversations)
    rsid = rows[0].recording_session_id

    head_candidates = [r for r in rows if r.id == rsid]
    if len(head_candidates) == 1:
        head = head_candidates[0]
    else:
        bare = [r for r in rows if r.previous_conversation_id is None]
        if len(bare) == 1:
            head = bare[0]
        else:
            return sorted(rows, key=lambda x: x.created_at)

    ordered: list[ConversationChainSegment] = [head]
    current = head
    seen: set[UUID] = {current.id}
    while True:
        nxt = next(
            (r for r in rows if r.previous_conversation_id == current.id),
            None,
        )
        if nxt is None:
            break
        if nxt.id in seen:
            break
        ordered.append(nxt)
        seen.add(nxt.id)
        current = nxt

    if len(ordered) != len(rows):
        rest = [r for r in rows if r.id not in seen]
        ordered.extend(sorted(rest, key=lambda x: x.created_at))
    return ordered
