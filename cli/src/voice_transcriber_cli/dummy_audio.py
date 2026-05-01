"""Minimal audio-like bytes for stub ASR when no file is given."""

DUMMY_WEBM: bytes = (
    b"\x1a\x45\xdf\xa3"  # EBML/WebM signature
    + b"\x00" * 512
)

DUMMY_MP3: bytes = b"\xff\xfb\x90\x00" + b"\x00" * 256

MIME_BY_EXT: dict[str, str] = {
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "opus": "audio/opus",
}
