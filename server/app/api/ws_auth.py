"""
WebSocket: извлечение JWT из query или Sec-WebSocket-Protocol (см. docs/WEBSOCKET.md).

C7.5 (prod): при **environment=production** параметр query `access_token` отклоняется —
только подпротокол `bearer.<JWT>` (токен не светится в URL и типичных логах пути).
"""

from __future__ import annotations

import os
from typing import Any, TYPE_CHECKING

from core.config import app_config

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import WebSocket


def _ws_subprotocol_only_required() -> bool:
    """
    Разрешить JWT только через Sec-WebSocket-Protocol (не через query).

    Включается если:
    - **VT_WS_REQUIRE_SUBPROTOCOL** = 1/true, или
    - **environment** из конфига (напр. `VT_ENVIRONMENT`) == `production`

    Явный выключатель для скриптов/legacy: **VT_WS_ALLOW_QUERY_TOKEN** = 1/true.
    """
    if os.environ.get("VT_WS_ALLOW_QUERY_TOKEN", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    if os.environ.get("VT_WS_REQUIRE_SUBPROTOCOL", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    env = (app_config.environment or "").strip().lower()
    return env == "production"


def extract_access_token_for_websocket(websocket: Any) -> tuple[str | None, str | None, str | None]:
    """
    Возвращает ``(token, subprotocol_for_accept, reject_reason)``.

    При непустом ``reject_reason`` соединение нужно закрыть до ``accept`` (код 1008).

    Приоритет при разрешённом query: query ``access_token``, иначе элемент ``bearer.<JWT>`` в
    Sec-WebSocket-Protocol. В режиме только subprotocol наличие непустого ``access_token`` в query
    → ``reject_reason=query_token_forbidden`` (даже если передан и bearer).
    """
    strict = _ws_subprotocol_only_required()
    q_raw = websocket.query_params.get("access_token")
    q = q_raw.strip() if isinstance(q_raw, str) else ""

    if q:
        if strict:
            return None, None, "query_token_forbidden"
        return q, None, None

    raw = websocket.headers.get("sec-websocket-protocol", "")
    if not raw:
        return None, None, "missing_token"

    for part in raw.split(","):
        p = part.strip()
        if p.lower().startswith("bearer."):
            tok = p[7:].strip()
            if tok:
                return tok, p, None
    return None, None, "missing_token"
