#!/usr/bin/env python3
"""
Strip torch/torchaudio/triton and nvidia-* lines from a pip requirements.txt
so torch can be installed separately (e.g. CPU wheels from download.pytorch.org).

PEP 508 lines with environment markers are preserved except for removed packages.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _package_name(line: str) -> str:
    """Return normalized distribution name for first requirement on a line."""
    s = line.strip()
    if not s or s.startswith("#"):
        return ""
    # Strip markers for name detection only
    main = s.split(";", 1)[0].strip()
    # URL/VCS specs — skip stripping logic (leave line in output)
    if " @ " in main or main.startswith("git+"):
        return ""
    # Remove extras [...]
    main = re.sub(r"\[.*?\]", "", main, count=1)
    m = re.match(r"^([a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?)", main)
    return m.group(1).lower() if m else ""


def _should_strip(name: str) -> bool:
    if name in ("torch", "torchaudio", "triton"):
        return True
    if name.startswith("nvidia-"):
        return True
    # CUDA stack helper wheels pulled in with PyPI torch; not needed for CPU torch install.
    if name.startswith("cuda-"):
        return True
    return False


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: diarization_strip_torch_cuda.py <requirements.txt> <out.txt>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    out_lines: list[str] = []
    for line in src.read_text(encoding="utf-8").splitlines():
        name = _package_name(line)
        if name and _should_strip(name):
            continue
        out_lines.append(line)
    dst.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
