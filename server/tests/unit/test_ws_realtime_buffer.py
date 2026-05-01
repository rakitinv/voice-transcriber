from app.api.ws_realtime_buffer import (
    RealtimeAudioBuffer,
    RealtimeBufferParams,
    clamp_chunk_ms,
    resolve_realtime_mode,
)


def test_chunk_mode_flushes_in_steps() -> None:
    p = RealtimeBufferParams(
        mode="chunk",
        chunk_ms=1000,
        max_window_ms=20_000,
        pcm_sample_rate=16_000,
    )
    buf = RealtimeAudioBuffer(p)
    step = buf._step_b
    out = buf.feed(b"x" * (step * 2 + step // 2))
    assert len(out) == 2
    assert len(out[0]) == step
    assert len(out[1]) == step


def test_clamp_chunk_ms() -> None:
    assert clamp_chunk_ms(None, 500, 2000) == 1250
    assert clamp_chunk_ms(100, 500, 2000) == 500
    assert clamp_chunk_ms(9999, 500, 2000) == 2000


def test_resolve_mode() -> None:
    assert resolve_realtime_mode("chunk", ("chunk", "windowed"), "windowed") == "chunk"
    assert resolve_realtime_mode(None, ("chunk", "windowed"), "windowed") == "windowed"
    assert resolve_realtime_mode("invalid", ("chunk", "windowed"), "chunk") == "chunk"
