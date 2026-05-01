"""HTTP client for Voice Transcriber REST API."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from .dummy_audio import DUMMY_MP3, DUMMY_WEBM, MIME_BY_EXT


def filename_from_content_disposition(header: str | None) -> str | None:
    if not header:
        return None
    m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\n]+)', header, re.I)
    if m:
        try:
            from urllib.parse import unquote

            return unquote(m.group(1).strip().strip('"'))
        except Exception:
            return m.group(1).strip().strip('"')
    m2 = re.search(r'filename="([^"]+)"', header)
    if m2:
        return m2.group(1)
    return None


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 120.0,
        token: str | None = None,
        api_key: str | None = None,
    ):
        self._base = base_url.rstrip("/")
        key = (api_key or "").strip()
        tok = (token or "").strip()
        if key:
            self._headers = {"X-VT-Api-Key": key}
        elif tok:
            self._headers = {"Authorization": f"Bearer {tok}"}
        else:
            raise ValueError("Either token or api_key is required")
        self._client = httpx.Client(trust_env=True, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._base}{path}"

    def _raise_for_status(self, r: httpx.Response, context: str) -> None:
        if r.is_success:
            return
        body = r.text[:4000] if r.text else ""
        try:
            data = r.json()
            detail = data.get("detail")
            if isinstance(detail, str):
                msg = f"{context}: HTTP {r.status_code} — {detail}"
            elif isinstance(detail, list):
                msg = f"{context}: HTTP {r.status_code} — {json.dumps(detail, ensure_ascii=False)[:500]}"
            else:
                msg = f"{context}: HTTP {r.status_code}"
        except Exception:
            msg = f"{context}: HTTP {r.status_code}"
        raise ApiError(msg, status_code=r.status_code, body=body) from None

    def me(self) -> dict[str, Any]:
        r = self._client.get(self._url("/api/auth/me"), headers=self._headers)
        self._raise_for_status(r, "auth/me")
        return r.json()

    def upload(
        self,
        *,
        file_path: Path | None,
        audio_format: str | None,
        conversation_id: str | None,
    ) -> dict[str, Any]:
        if file_path is None:
            ext = (audio_format or "webm").lower().lstrip(".")
            if ext == "mp3":
                data, name, mime = DUMMY_MP3, "clip.mp3", MIME_BY_EXT["mp3"]
            else:
                data, name, mime = DUMMY_WEBM, "clip.webm", MIME_BY_EXT["webm"]
        else:
            data = file_path.read_bytes()
            name = file_path.name
            suf = file_path.suffix.lower().lstrip(".")
            mime = MIME_BY_EXT.get(suf, "application/octet-stream")

        params: dict[str, str] = {}
        if audio_format:
            params["audio_format"] = audio_format.strip().lstrip(".")
        if conversation_id:
            params["conversation_id"] = conversation_id

        files = {"file": (name, data, mime)}
        r = self._client.post(
            self._url("/api/upload"),
            headers=self._headers,
            files=files,
            params=params or None,
        )
        if r.status_code == 401:
            raise ApiError(
                "401: JWT не принят API. Проверьте VT_ACCESS_TOKEN / --token "
                "(три части через точку; из Web UI — localStorage access_token).",
                status_code=401,
                body=r.text,
            )
        self._raise_for_status(r, "upload")
        return r.json()

    def list_conversations(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        recording_session_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if recording_session_id:
            params["recording_session_id"] = recording_session_id.strip()
        r = self._client.get(
            self._url("/api/conversations"),
            headers=self._headers,
            params=params,
        )
        self._raise_for_status(r, "conversations")
        return r.json()

    def create_conversation(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self._client.post(
            self._url("/api/conversations"),
            headers=self._headers,
            json=body if body else {},
        )
        self._raise_for_status(r, "conversations create")
        return r.json()

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        r = self._client.get(
            self._url(f"/api/conversations/{conversation_id}"),
            headers=self._headers,
        )
        self._raise_for_status(r, f"conversations/{conversation_id}")
        return r.json()

    def delete_conversation(self, conversation_id: str) -> None:
        r = self._client.delete(
            self._url(f"/api/conversations/{conversation_id}"),
            headers=self._headers,
        )
        if r.status_code == 204:
            return
        self._raise_for_status(r, "delete")

    def export_transcript(self, conversation_id: str, fmt: str) -> tuple[bytes, str | None]:
        r = self._client.get(
            self._url(f"/api/conversations/{conversation_id}/export"),
            headers=self._headers,
            params={"format": fmt},
        )
        self._raise_for_status(r, "export")
        cd = r.headers.get("content-disposition")
        return r.content, cd

    def download_audio(self, conversation_id: str) -> tuple[bytes, str | None]:
        r = self._client.get(
            self._url(f"/api/conversations/{conversation_id}/audio"),
            headers=self._headers,
        )
        self._raise_for_status(r, "audio")
        return r.content, r.headers.get("content-disposition")
