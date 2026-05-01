#!/usr/bin/env python3
"""
Сводный отчёт по аудио-пайплайну: POST /api/upload, затем проверки tier=fast/final и export.

Дополнительно (опция): WebSocket /ws/audio, finalize, проверки fast/final для realtime (docs/WEBSOCKET.md).

Окружение (как у A3.2 e2e):

  VT_E2E_BASE_URL или VT_API_BASE_URL — базовый URL API без хвоста /api (например http://127.0.0.1:8002).
  VT_E2E_TOKEN или VT_ACCESS_TOKEN — JWT пользователя.

Пример:

  cd server && .venv\\Scripts\\activate
  set VT_E2E_BASE_URL=http://127.0.0.1:8002
  set VT_E2E_TOKEN=<jwt>
  python ..\\scripts\\audio_acceptance_report.py clip.webm other.wav

Опции времени: VT_E2E_POLL_INTERVAL, VT_E2E_MAX_WAIT (как в pytest e2e).

Realtime (нужен пакет websockets: poetry install в server/):

  python ..\\scripts\\audio_acceptance_report.py --realtime-webm session.webm clip.webm

Код выхода: 0 если все проверки пройдены, иначе 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

try:
    import httpx
except ImportError as e:  # pragma: no cover
    print("Нужен пакет httpx (venv сервера): pip install httpx", file=sys.stderr)
    raise SystemExit(1) from e

DUMMY_WEBM: bytes = b"\x1a\x45\xdf\xa3" + b"\x00" * 512
_DUMMY_MP3: bytes = b"\xff\xfb\x90\x00" + b"\x00" * 256

_MIME_BY_EXT: dict[str, str] = {
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "opus": "audio/opus",
}


@dataclass
class CheckRow:
    scope: str
    check_id: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    rows: list[CheckRow] = field(default_factory=list)

    def add(self, scope: str, check_id: str, ok: bool, detail: str = "") -> None:
        self.rows.append(CheckRow(scope=scope, check_id=check_id, ok=ok, detail=detail))

    def all_ok(self) -> bool:
        return all(r.ok for r in self.rows)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _normalize_access_token(raw: str) -> str:
    t = raw.strip().strip('"').strip("'")
    if "#access_token=" in t:
        t = t.split("#access_token=", 1)[1]
    if "access_token=" in t and not t.startswith("eyJ"):
        t = t.split("access_token=", 1)[1]
    t = t.split("&", 1)[0].split("#", 1)[0]
    return unquote(t)


def _looks_like_jwt(token: str) -> bool:
    parts = [p for p in token.split(".") if p]
    return len(parts) == 3


def _http_to_ws_base(http_base: str) -> str:
    b = http_base.strip().rstrip("/")
    if b.lower().startswith("ws://"):
        return b
    if b.lower().startswith("wss://"):
        return b
    if b.startswith("https://"):
        return "wss://" + b[len("https://") :]
    if b.startswith("http://"):
        return "ws://" + b[len("http://") :]
    raise ValueError(f"Не удалось преобразовать базовый URL в ws(s): {http_base!r}")


def _resolve_token(cli_token: str) -> str:
    raw = (
        cli_token.strip()
        or os.environ.get("VT_E2E_TOKEN", "").strip()
        or os.environ.get("VT_ACCESS_TOKEN", "").strip()
    )
    if not raw:
        raise SystemExit(
            "Задайте JWT: VT_E2E_TOKEN, VT_ACCESS_TOKEN или аргумент --token."
        )
    tok = _normalize_access_token(raw)
    if not _looks_like_jwt(tok):
        raise SystemExit(
            "Токен не похож на JWT (ожидаются три сегмента через точку). "
            f"Начало: {tok[:48]!r}…"
        )
    return tok


def _resolve_base(cli_base: str) -> str:
    b = (
        cli_base.strip().rstrip("/")
        or os.environ.get("VT_E2E_BASE_URL", "").strip().rstrip("/")
        or os.environ.get("VT_API_BASE_URL", "").strip().rstrip("/")
    )
    if not b:
        raise SystemExit(
            "Задайте базовый URL API: VT_E2E_BASE_URL, VT_API_BASE_URL или --base-url."
        )
    return b


def upload_file(
    client: httpx.Client,
    base: str,
    token: str,
    file_path: Path,
    audio_format: str | None,
) -> tuple[str, int]:
    data = file_path.read_bytes()
    name = file_path.name
    suf = file_path.suffix.lower().lstrip(".")
    mime = _MIME_BY_EXT.get(suf, "application/octet-stream")
    params: dict[str, str] = {}
    if audio_format:
        params["audio_format"] = audio_format.strip().lstrip(".")
    r = client.post(
        f"{base}/api/upload",
        headers=_auth_headers(token),
        files={"file": (name, data, mime)},
        params=params or None,
        timeout=120.0,
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    cid = str(body.get("conversation_id") or "")
    return cid, r.status_code


def post_dummy_upload(
    client: httpx.Client,
    base: str,
    token: str,
    *,
    ext: str,
) -> tuple[str, int]:
    ext = ext.lower().lstrip(".")
    if ext == "mp3":
        data, name, mime = _DUMMY_MP3, "acceptance.mp3", _MIME_BY_EXT["mp3"]
    else:
        data, name, mime = DUMMY_WEBM, "acceptance.webm", _MIME_BY_EXT["webm"]
    r = client.post(
        f"{base}/api/upload",
        headers=_auth_headers(token),
        files={"file": (name, data, mime)},
        timeout=120.0,
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return str(body.get("conversation_id") or ""), r.status_code


def get_conversation(
    client: httpx.Client,
    base: str,
    token: str,
    cid: str,
    tier: str | None,
) -> tuple[dict, int]:
    params = {}
    if tier:
        params["tier"] = tier
    r = client.get(
        f"{base}/api/conversations/{cid}",
        headers=_auth_headers(token),
        params=params or None,
        timeout=60.0,
    )
    try:
        return r.json(), r.status_code
    except Exception:
        return {}, r.status_code


def export_conv(
    client: httpx.Client,
    base: str,
    token: str,
    cid: str,
    *,
    tier: str,
    fmt: str,
) -> tuple[int, str]:
    r = client.get(
        f"{base}/api/conversations/{cid}/export",
        headers=_auth_headers(token),
        params={"format": fmt, "tier": tier},
        timeout=60.0,
    )
    return r.status_code, r.text[:500]


def poll_until_transcript(
    client: httpx.Client,
    base: str,
    token: str,
    cid: str,
    *,
    tier: str | None,
    interval: float,
    max_wait: float,
) -> tuple[dict | None, bool]:
    deadline = time.monotonic() + max_wait
    last: dict | None = None
    while time.monotonic() < deadline:
        last, code = get_conversation(client, base, token, cid, tier)
        if code != 200:
            time.sleep(interval)
            continue
        segs = last.get("transcript") or []
        if len(segs) > 0:
            return last, True
        time.sleep(interval)
    return last, False


def run_upload_checks(
    report: Report,
    scope: str,
    client: httpx.Client,
    base: str,
    token: str,
    file_path: Path | None,
    *,
    dummy_ext: str | None,
    audio_format: str | None,
    interval: float,
    max_wait: float,
) -> str | None:
    if file_path is not None:
        cid, code = upload_file(client, base, token, file_path, audio_format)
        report.add(scope, "upload.http_accepted", code == 202, f"HTTP {code}")
    else:
        cid, code = post_dummy_upload(client, base, token, ext=dummy_ext or "webm")
        report.add(scope, "upload.http_accepted", code == 202, f"HTTP {code}")
    if not cid:
        report.add(scope, "upload.conversation_id", False, "нет conversation_id в ответе")
        return None
    report.add(scope, "upload.conversation_id", True, cid[:8] + "…")

    _detail, ok = poll_until_transcript(
        client, base, token, cid, tier=None, interval=interval, max_wait=max_wait
    )
    report.add(
        scope,
        "upload.poll_auto_nonempty",
        ok,
        "есть сегменты" if ok else f"таймаут {max_wait}s",
    )
    if not ok:
        return cid

    fast_body, fc = get_conversation(client, base, token, cid, "fast")
    fast_segs = (fast_body.get("transcript") or []) if fc == 200 else []
    report.add(
        scope,
        "upload.get_tier_fast_empty",
        fc == 200 and len(fast_segs) == 0,
        f"HTTP {fc}, сегментов={len(fast_segs)}",
    )

    fin_body, fic = get_conversation(client, base, token, cid, "final")
    fin_segs = (fin_body.get("transcript") or []) if fic == 200 else []
    report.add(
        scope,
        "upload.get_tier_final_nonempty",
        fic == 200 and len(fin_segs) > 0,
        f"HTTP {fic}, сегментов={len(fin_segs)}",
    )

    ej_code, _ej = export_conv(client, base, token, cid, tier="final", fmt="json")
    report.add(
        scope,
        "upload.export_final_json",
        ej_code == 200,
        f"HTTP {ej_code}",
    )

    xf_code, _xf = export_conv(client, base, token, cid, tier="fast", fmt="json")
    report.add(
        scope,
        "upload.export_fast_404",
        xf_code == 404,
        f"HTTP {xf_code} (ожидается 404 без fast-ветки)",
    )

    return cid


async def run_realtime_checks(
    report: Report,
    scope: str,
    http_base: str,
    token: str,
    webm_path: Path,
    *,
    client: httpx.Client,
    interval: float,
    max_wait: float,
) -> None:
    try:
        import websockets
    except ImportError:
        report.add(
            scope,
            "realtime.import_websockets",
            False,
            "pip install websockets или poetry install (group dev) в server/",
        )
        return

    ws_base = _http_to_ws_base(http_base)
    r = client.post(
        f"{http_base}/api/conversations",
        headers=_auth_headers(token),
        json={"title": "acceptance-realtime"},
        timeout=30.0,
    )
    if r.status_code != 201:
        report.add(
            scope,
            "realtime.create_conversation",
            False,
            f"HTTP {r.status_code} {r.text[:200]}",
        )
        return
    cid = str(r.json().get("id") or "")
    report.add(scope, "realtime.create_conversation", bool(cid), cid[:8] + "…" if cid else "")
    if not cid:
        return

    uri = f"{ws_base}/ws/audio/{cid}"
    ws_proto = f"bearer.{token}"

    audio = webm_path.read_bytes()
    finalize_id = str(uuid.uuid4())

    try:
        async with websockets.connect(
            uri,
            subprotocols=[ws_proto],
            open_timeout=30,
            close_timeout=10,
        ) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            try:
                hello = json.loads(raw)
            except Exception:
                hello = {}
            report.add(
                scope,
                "realtime.ws_ready",
                hello.get("type") == "ready",
                str(hello.get("type")),
            )

            chunk_sz = 64 * 1024
            for i in range(0, len(audio), chunk_sz):
                await ws.send(audio[i : i + chunk_sz])
                await asyncio.sleep(0.02)

            await ws.send(
                json.dumps({"type": "finalize", "finalize_id": finalize_id}, ensure_ascii=False)
            )

            got_ack = False
            status_ok = False
            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline:
                try:
                    raw2 = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    msg = json.loads(raw2)
                except Exception:
                    continue
                if msg.get("type") == "finalize_ack" and msg.get("finalize_id") == finalize_id:
                    got_ack = True
                    status_ok = msg.get("status") == "accepted"
                    break
                if msg.get("type") == "finalize_error":
                    report.add(
                        scope,
                        "realtime.finalize_ack",
                        False,
                        msg.get("detail", raw2[:300]),
                    )
                    return

            report.add(
                scope,
                "realtime.finalize_ack",
                got_ack and status_ok,
                "accepted" if status_ok else ("нет ack" if not got_ack else "не accepted"),
            )
            if not (got_ack and status_ok):
                return

    except Exception as e:
        report.add(scope, "realtime.ws_session", False, str(e)[:400])
        return

    deadline = time.monotonic() + max_wait
    fast_nonempty = False
    fin_nonempty = False
    last_fast_n = last_fin_n = 0
    while time.monotonic() < deadline:
        fb, fc = get_conversation(client, http_base, token, cid, "fast")
        if fc == 200:
            last_fast_n = len(fb.get("transcript") or [])
            if last_fast_n > 0:
                fast_nonempty = True
                break
        time.sleep(interval)

    report.add(
        scope,
        "realtime.poll_fast_nonempty",
        fast_nonempty,
        f"сегментов={last_fast_n}" + ("" if fast_nonempty else f" (таймаут {max_wait}s)"),
    )

    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        fb, fc = get_conversation(client, http_base, token, cid, "final")
        if fc == 200:
            last_fin_n = len(fb.get("transcript") or [])
            if last_fin_n > 0:
                fin_nonempty = True
                break
        time.sleep(interval)

    report.add(
        scope,
        "realtime.poll_final_nonempty",
        fin_nonempty,
        f"сегментов={last_fin_n}" + ("" if fin_nonempty else f" (таймаут {max_wait}s)"),
    )

    ec_f, _ = export_conv(client, http_base, token, cid, tier="fast", fmt="json")
    ec_j, _ = export_conv(client, http_base, token, cid, tier="final", fmt="json")
    report.add(
        scope,
        "realtime.export_fast_200",
        ec_f == 200,
        f"HTTP {ec_f}",
    )
    report.add(
        scope,
        "realtime.export_final_200",
        ec_j == 200,
        f"HTTP {ec_j}",
    )


def print_table(report: Report) -> None:
    scope_w = max((len(r.scope) for r in report.rows), default=8)
    id_w = max((len(r.check_id) for r in report.rows), default=20)
    head_scope = "Файл / этап".ljust(scope_w)
    head_id = "Проверка".ljust(id_w)
    print(f"{head_scope}  {head_id}  Результат  Примечание")
    print("-" * (scope_w + id_w + 40))
    for row in report.rows:
        mark = "OK" if row.ok else "FAIL"
        det = row.detail.replace("\n", " ")
        print(
            f"{row.scope.ljust(scope_w)}  {row.check_id.ljust(id_w)}  {mark.ljust(9)}  {det}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--base-url",
        default="",
        help="Базовый URL API. Env: VT_E2E_BASE_URL, VT_API_BASE_URL",
    )
    ap.add_argument("--token", default="", help="JWT. Env: VT_E2E_TOKEN, VT_ACCESS_TOKEN")
    ap.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Локальные аудиофайлы для upload-сценария (если пусто — заглушка webm)",
    )
    ap.add_argument(
        "--dummy-format",
        choices=("webm", "mp3"),
        default="webm",
        help="Расширение встроенной заглушки, если files не заданы",
    )
    ap.add_argument(
        "--audio-format",
        default=os.environ.get("VT_UPLOAD_AUDIO_FORMAT") or "",
        help="Query audio_format для upload",
    )
    ap.add_argument("--interval", type=float, default=float(os.environ.get("VT_E2E_POLL_INTERVAL", "2")))
    ap.add_argument("--max-wait", type=float, default=float(os.environ.get("VT_E2E_MAX_WAIT", "120")))
    ap.add_argument(
        "--realtime-webm",
        type=Path,
        default=None,
        help="Файл WebM для сценария WS + finalize (после проверок upload)",
    )
    ap.add_argument(
        "--json-out",
        action="store_true",
        help="Печатать Machine-readable JSON в stdout после таблицы",
    )
    args = ap.parse_args()

    base = _resolve_base(args.base_url)
    token = _resolve_token(args.token)
    audio_fmt = args.audio_format.strip() or None

    report = Report()
    timeout = httpx.Timeout(120.0, connect=30.0)

    file_list = list(args.files)
    if not file_list:
        file_list = [None]  # type: ignore[list-item]

    with httpx.Client(timeout=timeout, trust_env=True) as client:
        for fp in file_list:
            scope = fp.name if fp is not None else f"dummy.{args.dummy_format}"
            if fp is not None and not fp.is_file():
                report.add(scope, "upload.file_exists", False, str(fp))
                continue
            run_upload_checks(
                report,
                scope,
                client,
                base,
                token,
                fp,
                dummy_ext=args.dummy_format if fp is None else None,
                audio_format=audio_fmt,
                interval=args.interval,
                max_wait=args.max_wait,
            )

        if args.realtime_webm is not None:
            rp = args.realtime_webm
            if not rp.is_file():
                report.add(str(rp), "realtime.file_exists", False, str(rp))
            else:
                asyncio.run(
                    run_realtime_checks(
                        report,
                        rp.name,
                        base,
                        token,
                        rp,
                        client=client,
                        interval=args.interval,
                        max_wait=args.max_wait,
                    )
                )

    print_table(report)

    if args.json_out:
        payload = {
            "exit_ok": report.all_ok(),
            "checks": [
                {
                    "scope": r.scope,
                    "id": r.check_id,
                    "ok": r.ok,
                    "detail": r.detail,
                }
                for r in report.rows
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    raise SystemExit(0 if report.all_ok() else 1)


if __name__ == "__main__":
    main()
