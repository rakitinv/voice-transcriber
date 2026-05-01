"""
Нормализация формата загружаемого аудио (расширение объекта в S3 и суффикс для ASR).

Приоритет: явный query `audio_format` → расширение имени файла → Content-Type → webm.
"""

from __future__ import annotations

from pathlib import Path

# Ниже этого размера (байты исходного файла до шифрования в S3) реальный записанный WebM/и т.д.
# практически не встречается; типичны усечённые тела запроса или пустая запись. Отсекаем, чтобы
# не класть в S3 «битый» объект и не зависать в ffmpeg/ASR.
MIN_AUDIO_CONTENT_BYTES: int = 800

# Расширения без точки, нижний регистр (ключи для S3: audio.<ext>)
ALLOWED_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {"webm", "wav", "mp3", "m4a", "aac", "ogg", "flac", "opus"}
)

_CONTENT_TYPE_TO_EXT: dict[str, str] = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/opus": "opus",
    "audio/x-flac": "flac",
}


class AudioFormatError(ValueError):
    """Недопустимое или нераспознаваемое расширение / MIME."""


def resolve_audio_extension(
    *,
    explicit: str | None,
    filename: str | None,
    content_type: str | None,
) -> str:
    """
    Вернуть расширение файла без точки (например webm, mp3).

    Raises:
        AudioFormatError: если явно указан неподдерживаемый формат.
    """
    if explicit is not None and explicit.strip():
        ext = explicit.strip().lower().lstrip(".")
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise AudioFormatError(
                f"audio_format must be one of {sorted(ALLOWED_AUDIO_EXTENSIONS)}, got {ext!r}"
            )
        return ext

    if filename:
        suf = Path(filename).suffix.lower().lstrip(".")
        if suf and suf in ALLOWED_AUDIO_EXTENSIONS:
            return suf

    if content_type:
        # убрать параметры вроде charset
        base = content_type.split(";", 1)[0].strip().lower()
        if base in _CONTENT_TYPE_TO_EXT:
            return _CONTENT_TYPE_TO_EXT[base]

    return "webm"


def s3_audio_object_name(ext: str) -> str:
    """Имя объекта в префиксе разговора (например audio.mp3)."""
    e = ext.lower().lstrip(".")
    if e not in ALLOWED_AUDIO_EXTENSIONS:
        raise AudioFormatError(f"Invalid audio extension for storage: {ext!r}")
    return f"audio.{e}"
