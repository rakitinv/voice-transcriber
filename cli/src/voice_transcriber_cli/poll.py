"""Poll GET /api/conversations/{id} until transcript has segments."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from .api import ApiClient, ApiError


def wait_for_transcript(
    client: ApiClient,
    conversation_id: str,
    *,
    interval: float,
    max_wait: float,
    verbose: bool = True,
) -> dict[str, Any]:
    deadline = time.monotonic() + max_wait
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            last = client.get_conversation(conversation_id)
        except ApiError as e:
            if verbose:
                print(str(e), file=sys.stderr)
            raise
        segs = last.get("transcript") or []
        if len(segs) > 0:
            if verbose:
                print(f"poll: transcript ready, segments: {len(segs)}", file=sys.stderr)
            return last
        if verbose:
            print(f"poll: transcript empty, waiting {interval}s...", file=sys.stderr)
        time.sleep(interval)
    snippet = json.dumps(last, indent=2, ensure_ascii=False)[:2000] if last else "null"
    raise TimeoutError(
        f"Timeout {max_wait}s: transcript did not appear.\n"
        "Check Celery worker, Redis, and worker logs.\n"
        f"Last GET /api/conversations/{conversation_id}:\n{snippet}"
    )
