from __future__ import annotations

import argparse
import os
import sys

from core.config import app_config
from core.logging import logger


def _apply_cache_offline_env(cache_dir: str | None, offline: bool) -> None:
    cache_dir = (cache_dir or "").strip()
    if cache_dir:
        os.environ.setdefault("HF_HOME", cache_dir)
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache_dir)
        os.environ.setdefault("TRANSFORMERS_CACHE", cache_dir)
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

def _apply_hf_token_env(hf_token: str) -> None:
    """
    huggingface_hub removed the legacy `use_auth_token=` kwarg in newer versions.
    Prefer passing the token via standard environment variables so downstream
    libraries (pyannote/transformers/huggingface_hub) can pick it up.
    """
    hf_token = (hf_token or "").strip()
    if not hf_token:
        return
    # Both are understood by huggingface_hub depending on version/config.
    if not os.environ.get("HUGGINGFACE_HUB_TOKEN", "").strip():
        os.environ["HUGGINGFACE_HUB_TOKEN"] = hf_token
    if not os.environ.get("HF_TOKEN", "").strip():
        os.environ["HF_TOKEN"] = hf_token


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Warm up / validate diarization model cache.")
    p.add_argument(
        "--provider",
        default=None,
        help="Override diarization provider name (default: config default_provider)",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="Force offline mode (no network).",
    )
    p.add_argument(
        "--online",
        action="store_true",
        help="Force online mode (allow network).",
    )
    args = p.parse_args(argv)

    name = (args.provider or app_config.diarization.default_provider or "").strip()
    if not name:
        logger.error("No diarization.default_provider configured")
        return 2

    cfg = app_config.diarization.providers.get(name)
    if not cfg or not cfg.enabled:
        logger.error("Diarization provider %s is not enabled/configured", name)
        return 2

    offline = bool(cfg.offline_models)
    if args.offline:
        offline = True
    if args.online:
        offline = False

    cache_dir = cfg.model_cache_dir
    _apply_cache_offline_env(cache_dir, offline=offline)

    model = (cfg.model or "pyannote/speaker-diarization-3.1").strip()
    token_env = (cfg.hf_token_env or "").strip()
    hf_token = os.environ.get(token_env, "").strip() if token_env else ""
    _apply_hf_token_env(hf_token)

    # In offline mode we intentionally do not require token; the cache must already exist.
    if not offline and not hf_token:
        logger.warning(
            "HF token env %s is empty; model download may fail if repo is gated",
            token_env,
        )

    if offline and not cache_dir:
        logger.error("offline mode requires model_cache_dir to be configured")
        return 2

    # PyTorch 2.6+ defaults `torch.load(weights_only=True)` for security.
    # Some upstream checkpoints (incl. pyannote) may require allowlisting additional
    # globals (e.g. TorchVersion / pyannote Specifications) even when loading trusted
    # model weights.
    try:
        import torch  # type: ignore

        add_safe = getattr(getattr(torch, "serialization", None), "add_safe_globals", None)
        if callable(add_safe):
            from torch.torch_version import TorchVersion  # type: ignore

            allow = [TorchVersion]
            try:
                import inspect
                import pyannote.audio.core.task as task  # type: ignore

                allow.extend(
                    [
                        obj
                        for obj in vars(task).values()
                        if inspect.isclass(obj) and getattr(obj, "__module__", "") == task.__name__
                    ]
                )
            except Exception:
                pass
            add_safe(allow)
    except Exception:
        # Best-effort: warmup may still succeed depending on torch/model versions.
        pass

    try:
        from pyannote.audio import Pipeline  # type: ignore
    except Exception as e:
        logger.error("pyannote.audio is not installed: %s", e)
        return 2

    logger.info(
        "Warming up diarization model: provider=%s model=%s offline=%s cache_dir=%s",
        name,
        model,
        offline,
        cache_dir,
    )
    try:
        _ = Pipeline.from_pretrained(model)
    except Exception as e:
        logger.error("Warmup failed: %s", e)
        return 1

    logger.info("Warmup OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

