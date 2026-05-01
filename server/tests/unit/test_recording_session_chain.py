"""Ordering §7 recording_session chains."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core.recording_session_chain import ordered_chain_segments


def test_ordered_chain_simple_three_segments():
    a = uuid4()
    b = uuid4()
    c = uuid4()
    rsid = a  # §7: first conversation id equals recording_session_id

    class Seg:
        pass

    # Head §7: id == recording_session_id
    s0 = Seg()
    s0.id = a
    s0.recording_session_id = rsid
    s0.previous_conversation_id = None
    s0.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    s1 = Seg()
    s1.id = b
    s1.recording_session_id = rsid
    s1.previous_conversation_id = a
    s1.created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)

    s2 = Seg()
    s2.id = c
    s2.recording_session_id = rsid
    s2.previous_conversation_id = b
    s2.created_at = datetime(2026, 1, 3, tzinfo=timezone.utc)

    ordered = ordered_chain_segments([s2, s0, s1])
    assert [x.id for x in ordered] == [a, b, c]  # a→b→c


def test_ordered_chain_single():
    rsid = uuid4()

    class Seg:
        pass

    s = Seg()
    s.id = rsid
    s.recording_session_id = rsid
    s.previous_conversation_id = None
    s.created_at = datetime.now(timezone.utc)

    ordered = ordered_chain_segments([s])
    assert len(ordered) == 1 and ordered[0].id == rsid
