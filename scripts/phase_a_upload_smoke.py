#!/usr/bin/env python3
"""
Сквозной сценарий Phase A: POST /api/upload → poll GET /api/conversations/{id} до появления transcript.

Для постоянной работы из командной строки установите CLI: cd cli && pip install -e .
и используйте команду «transcriber upload …» (см. cli/README.md).

Требуется JWT: переменная VT_ACCESS_TOKEN или --token. В Web UI он в localStorage «access_token»,
не в cookie «token» (cookie token/session — обычно не наш API-JWT).
Удобнее запускать из venv сервера (там уже есть httpx):

  cd server
  .\\.venv\\Scripts\\activate
  $env:VT_ACCESS_TOKEN = "<jwt из #access_token=... после логина>"
  python ..\\scripts\\phase_a_upload_smoke.py --base-url http://127.0.0.1:8002

Без --file подставляется минимальный заглушечный .webm (для stub ASR содержимое не декодируется).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote

try:
    import httpx
except ImportError as e:  # pragma: no cover
    print("Нужен пакет httpx: pip install httpx или активируйте venv в server/", file=sys.stderr)
    raise SystemExit(1) from e

# Минимальные байты с именем audio.webm: stub ASR не вызывает реальный декодер при отсутствии провайдера.
DUMMY_WEBM: bytes = (
    b"\x1a\x45\xdf\xa3"  # EBML/WebM signature start
    + b"\x00" * 512
)

_DUMMY_MP3: bytes = b"\xff\xfb\x90\x00" + b"\x00" * 256  # заголовок кадра MP3 + паддинг (stub)

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


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _normalize_access_token(raw: str) -> str:
    """Убрать обёртки URL/фрагмента; применить URL-decode (редирект OAuth кодирует JWT)."""
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


def upload(
    client: httpx.Client,
    base: str,
    token: str,
    file_path: Path | None,
    audio_format: str | None,
) -> str:
    if file_path is None:
        ext = (audio_format or "webm").lower().lstrip(".")
        if ext == "mp3":
            data, name, mime = _DUMMY_MP3, "clip.mp3", _MIME_BY_EXT["mp3"]
        else:
            data, name, mime = DUMMY_WEBM, "clip.webm", _MIME_BY_EXT["webm"]
    else:
        data = file_path.read_bytes()
        name = file_path.name
        suf = file_path.suffix.lower().lstrip(".")
        mime = _MIME_BY_EXT.get(suf, "application/octet-stream")

    params: dict[str, str] = {}
    if audio_format:
        params["audio_format"] = audio_format.strip().lstrip(".")

    files = {"file": (name, data, mime)}
    r = client.post(
        f"{base.rstrip('/')}/api/upload",
        headers=_auth_headers(token),
        files=files,
        params=params or None,
        timeout=120.0,
    )
    if r.status_code == 401:
        raise SystemExit(
            "401: токен не принят API.\n"
            "  • JWT выглядит как три части через точку: eyJ....eyJ....Sfl...\n"
            "  • Берите значение только после #access_token= в адресе Web UI (без префикса login).\n"
            "  • В PowerShell удобнее: $env:VT_ACCESS_TOKEN = '...весь JWT одной строкой...'\n"
            "  • Токен и секрет сервера (JWT в docker vs локальный API) должны совпадать."
        )
    r.raise_for_status()
    body = r.json()
    cid = body.get("conversation_id")
    if not cid:
        raise SystemExit(f"Неожиданный ответ upload: {body}")
    print(f"upload: HTTP {r.status_code}")
    print(json.dumps(body, indent=2, ensure_ascii=False))
    return str(cid)


def poll_detail(
    client: httpx.Client,
    base: str,
    token: str,
    conversation_id: str,
    interval: float,
    max_wait: float,
) -> dict:
    deadline = time.monotonic() + max_wait
    url = f"{base.rstrip('/')}/api/conversations/{conversation_id}"
    last: dict | None = None
    while time.monotonic() < deadline:
        r = client.get(url, headers=_auth_headers(token), timeout=60.0)
        r.raise_for_status()
        last = r.json()
        segs = last.get("transcript") or []
        if len(segs) > 0:
            print(f"poll: transcript готов, сегментов: {len(segs)}")
            return last
        print(f"poll: transcript пустой, ждём {interval}s…")
        time.sleep(interval)
    raise SystemExit(
        f"Таймаут {max_wait}s: transcript не появился.\n"
        "Проверьте:\n"
        "  • Контейнер/процесс Celery **worker** запущен и слушает очередь **asr** (тот же Redis, что у API).\n"
        "  • После обновления кода API/worker пересобраны: **docker compose build worker api** (иначе worker падает на kwargs или не качает новый S3-ключ).\n"
        "  • Логи: **docker compose logs -f worker** (или локальный celery worker).\n"
        "Последний ответ GET /api/conversations/{id}:\n"
        + json.dumps(last, indent=2, ensure_ascii=False)[:2000]
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--base-url",
        default=os.environ.get("VT_API_BASE_URL", "http://127.0.0.1:8002"),
        help="Базовый URL API (без завершающего /). Env: VT_API_BASE_URL",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("VT_ACCESS_TOKEN", ""),
        help="JWT. Env: VT_ACCESS_TOKEN",
    )
    p.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Локальный файл аудио (иначе встроенная заглушка webm или mp3 при --audio-format mp3)",
    )
    p.add_argument(
        "--audio-format",
        default=os.environ.get("VT_UPLOAD_AUDIO_FORMAT"),
        help="Query audio_format (явный формат). Env: VT_UPLOAD_AUDIO_FORMAT",
    )
    p.add_argument("--interval", type=float, default=2.0, help="Интервал опроса, сек")
    p.add_argument("--max-wait", type=float, default=120.0, help="Максимум ожидания transcript")
    args = p.parse_args()

    if not args.token.strip():
        raise SystemExit(
            "Задайте JWT: переменная VT_ACCESS_TOKEN или --token …\n"
            "Токен из URL Web UI после Google: .../login#access_token=<JWT>"
        )

    token = _normalize_access_token(args.token)
    if not _looks_like_jwt(token):
        raise SystemExit(
            "VT_ACCESS_TOKEN не похож на JWT (ожидаются ровно три сегмента, разделённые точкой «.»).\n"
            "Скопируйте только строку после «access_token=» из фрагмента URL (часто начинается с «eyJ»).\n"
            f"Сейчас (первые 60 символов): {token[:60]!r}…"
        )

    if args.file is not None and not args.file.is_file():
        raise SystemExit(f"Файл не найден: {args.file}")

    with httpx.Client(trust_env=True) as client:
        af = (args.audio_format or "").strip() or None
        cid = upload(client, args.base_url, token, args.file, af)
        detail = poll_detail(
            client,
            args.base_url,
            token,
            cid,
            args.interval,
            args.max_wait,
        )

    print("--- conversation (фрагмент) ---")
    print(json.dumps({k: detail[k] for k in ("id", "title", "transcript") if k in detail}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
