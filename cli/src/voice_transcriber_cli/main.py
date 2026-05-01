"""CLI entry: argparse + dispatch."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

from . import __version__
from .api import ApiClient, ApiError, filename_from_content_disposition
from .poll import wait_for_transcript
from .tokens import looks_like_jwt, normalize_access_token


def _die(msg: str, code: int = 1) -> NoReturn:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _require_auth(args: argparse.Namespace) -> dict[str, str]:
    api_key = (args.api_key or "").strip()
    token_raw = (args.token or "").strip()
    if api_key:
        return {"api_key": api_key}
    if not token_raw:
        _die(
            "Set JWT: VT_ACCESS_TOKEN / --token\n"
            "or API key: VT_API_KEY / --api-key (header X-VT-Api-Key)."
        )
    token = normalize_access_token(token_raw)
    if not looks_like_jwt(token):
        _die(
            "Token does not look like a JWT (expect three segments separated by dots).\n"
            f"First 60 chars: {token[:60]!r}..."
        )
    return {"token": token}


def _cmd_me(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.me()
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    uid = data.get("id", "?")
    email = data.get("email", "")
    name = data.get("name", "")
    print(f"id:   {uid}")
    if email:
        print(f"email: {email}")
    if name:
        print(f"name:  {name}")


def _omit_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _cmd_upload(client: ApiClient, args: argparse.Namespace) -> None:
    if args.file is not None and not args.file.is_file():
        _die(f"File not found: {args.file}")

    af = (args.audio_format or "").strip() or None
    body = client.upload(
        file_path=args.file,
        audio_format=af,
        conversation_id=(args.conversation_id or "").strip() or None,
    )
    cid = str(body.get("conversation_id", ""))
    if not cid:
        _die(f"Unexpected upload response: {body}")

    print(json.dumps(body, indent=2, ensure_ascii=False))
    if not args.wait:
        return

    try:
        detail = wait_for_transcript(
            client,
            cid,
            interval=args.interval,
            max_wait=args.max_wait,
            verbose=not args.quiet,
        )
    except TimeoutError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(124) from e
    frag = {k: detail[k] for k in ("id", "title", "transcript") if k in detail}
    print("--- conversation (excerpt) ---")
    print(json.dumps(frag, indent=2, ensure_ascii=False))


def _cmd_conversations_create(client: ApiClient, args: argparse.Namespace) -> None:
    body = _omit_none(
        {
            "title": args.title,
            "ttl_days": args.ttl_days,
            "realtime_mode": args.realtime_mode,
            "chunk_ms": args.chunk_ms,
            "previous_conversation_id": args.previous_conversation_id,
            "recording_session_id": args.recording_session_id,
        }
    )
    data = client.create_conversation(body)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _cmd_conversations_chain(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.list_conversations(
        skip=args.skip,
        limit=args.limit,
        recording_session_id=args.recording_session_id,
    )
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    rows = data.get("conversations") or []
    total = data.get("total", len(rows))
    print(f"session {args.recording_session_id} — total: {total}")
    for c in rows:
        cid = c.get("id")
        prev = c.get("previous_conversation_id")
        title = c.get("title") or ""
        created = c.get("created_at", "")
        print(f"  {cid}  prev={prev}  {created}  {title[:60]}")


def _cmd_conversations_list(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.list_conversations(skip=args.skip, limit=args.limit)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    rows = data.get("conversations") or []
    total = data.get("total", len(rows))
    print(f"total: {total}")
    for c in rows:
        cid = c.get("id")
        title = c.get("title") or ""
        created = c.get("created_at", "")
        ext = c.get("audio_object_ext", "")
        print(f"  {cid}  {created}  {ext!r}  {title[:60]}")


def _cmd_conversations_show(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get_conversation(args.conversation_id)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _cmd_export(client: ApiClient, args: argparse.Namespace) -> None:
    content, _cd = client.export_transcript(args.conversation_id, args.format)
    if args.output:
        args.output.write_bytes(content)
        print(f"Wrote {len(content)} bytes to {args.output}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(content)


def _cmd_audio(client: ApiClient, args: argparse.Namespace) -> None:
    content, cd = client.download_audio(args.conversation_id)
    out = args.output
    if out is None:
        name = filename_from_content_disposition(cd) or f"recording-{args.conversation_id}.bin"
        out = Path(name)
    out.write_bytes(content)
    print(f"Wrote {len(content)} bytes to {out}", file=sys.stderr)


def _cmd_delete(client: ApiClient, args: argparse.Namespace) -> None:
    client.delete_conversation(args.conversation_id)
    print(f"Deleted {args.conversation_id}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transcriber",
        description="Voice Transcriber API: upload, list, export (same contract as Web UI).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--base-url",
        default=os.environ.get("VT_API_BASE_URL", "http://127.0.0.1:8002"),
        help="API base URL without trailing slash. Env: VT_API_BASE_URL",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("VT_ACCESS_TOKEN", ""),
        help="Bearer JWT. Env: VT_ACCESS_TOKEN",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("VT_API_KEY", ""),
        help="REST header X-VT-Api-Key (alternative to JWT). Env: VT_API_KEY",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP client timeout in seconds",
    )

    sub = p.add_subparsers(dest="command", required=True)

    sp_me = sub.add_parser("me", help="Show current user (GET /api/auth/me)")
    sp_me.add_argument("--json", action="store_true", help="Raw JSON")
    sp_me.set_defaults(func=_cmd_me)

    sp_up = sub.add_parser("upload", help="Upload audio (POST /api/upload)")
    sp_up.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="Local audio file (optional: built-in stub webm/mp3)",
    )
    sp_up.add_argument(
        "--audio-format",
        default=os.environ.get("VT_UPLOAD_AUDIO_FORMAT"),
        help="Query audio_format. Env: VT_UPLOAD_AUDIO_FORMAT",
    )
    sp_up.add_argument("--conversation-id", help="Attach to existing conversation UUID")
    sp_up.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not poll until transcript is ready",
    )
    sp_up.add_argument("--interval", type=float, default=2.0, help="Poll interval (seconds)")
    sp_up.add_argument("--max-wait", type=float, default=120.0, help="Max wait for transcript")
    sp_up.add_argument(
        "--quiet",
        action="store_true",
        help="Less poll progress on stderr",
    )
    sp_up.set_defaults(func=_cmd_upload)

    sp_cv = sub.add_parser("conversations", help="List or show conversations")
    cv_sub = sp_cv.add_subparsers(dest="conv_cmd", required=True)

    sp_list = cv_sub.add_parser("list", help="GET /api/conversations")
    sp_list.add_argument("--skip", type=int, default=0)
    sp_list.add_argument("--limit", type=int, default=50)
    sp_list.add_argument("--json", action="store_true")
    sp_list.set_defaults(func=_cmd_conversations_list)

    sp_cr = cv_sub.add_parser("create", help="POST /api/conversations")
    sp_cr.add_argument("--title")
    sp_cr.add_argument("--ttl-days", type=int, dest="ttl_days")
    sp_cr.add_argument("--realtime-mode", choices=["chunk", "windowed"], dest="realtime_mode")
    sp_cr.add_argument("--chunk-ms", type=int, dest="chunk_ms")
    sp_cr.add_argument("--previous-conversation-id", dest="previous_conversation_id")
    sp_cr.add_argument("--recording-session-id", dest="recording_session_id")
    sp_cr.add_argument("--json", action="store_true")
    sp_cr.set_defaults(func=_cmd_conversations_create)

    sp_chain = cv_sub.add_parser(
        "chain",
        help="List conversations with same recording_session_id (§7)",
    )
    sp_chain.add_argument("recording_session_id", help="UUID recording_session_id")
    sp_chain.add_argument("--skip", type=int, default=0)
    sp_chain.add_argument("--limit", type=int, default=50)
    sp_chain.add_argument("--json", action="store_true")
    sp_chain.set_defaults(func=_cmd_conversations_chain)

    sp_show = cv_sub.add_parser("show", help="GET /api/conversations/{id}")
    sp_show.add_argument("conversation_id", help="UUID")
    sp_show.add_argument("--json", action="store_true")
    sp_show.set_defaults(func=_cmd_conversations_show)

    sp_ex = sub.add_parser("export", help="Export transcript (GET .../export)")
    sp_ex.add_argument("conversation_id")
    sp_ex.add_argument("--format", choices=["md", "json"], required=True)
    sp_ex.add_argument("-o", "--output", type=Path, help="Output file (default: stdout)")
    sp_ex.set_defaults(func=_cmd_export)

    sp_au = sub.add_parser("audio", help="Download original audio (GET .../audio)")
    sp_au.add_argument("conversation_id")
    sp_au.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file (default: name from Content-Disposition or recording-<id>.bin)",
    )
    sp_au.set_defaults(func=_cmd_audio)

    sp_del = sub.add_parser("delete", help="Delete conversation (DELETE /api/conversations/{id})")
    sp_del.add_argument("conversation_id")
    sp_del.set_defaults(func=_cmd_delete)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)

    if hasattr(args, "no_wait"):
        args.wait = not args.no_wait

    auth = _require_auth(args)

    try:
        with ApiClient(args.base_url, timeout=args.timeout, **cast(Any, auth)) as client:
            func: Any = args.func
            func(client, args)
    except ApiError as e:
        print(str(e), file=sys.stderr)
        if e.body:
            print(e.body[:2000], file=sys.stderr)
        return 1
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as e:  # pragma: no cover
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
