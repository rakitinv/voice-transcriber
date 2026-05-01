import subprocess

import pytest

from core.webm_pcm import ffmpeg_binary, webm_to_pcm_one_shot


@pytest.mark.skipif(not ffmpeg_binary(), reason="ffmpeg not on PATH")
def test_webm_to_pcm_minimal() -> None:
    r = subprocess.run(
        [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            "0.2",
            "-c:a",
            "libopus",
            "-f",
            "webm",
            "pipe:1",
        ],
        capture_output=True,
        timeout=30,
        check=True,
    )
    webm = r.stdout
    pcm = webm_to_pcm_one_shot(webm)
    # 0.2 s * 16000 Hz * 2 bytes ≈ 6400, допуск на заголовки
    assert len(pcm) >= 4000
