#!/usr/bin/env bash
# Retry pip when large wheel downloads fail (sleep, VPN drop, IncompleteRead).
# Usage: pip-retry.sh install package …
set -euo pipefail

MAX="${PIP_RETRY_MAX:-5}"
PAUSE="${PIP_RETRY_PAUSE_SEC:-20}"

if [ "$#" -lt 1 ]; then
  echo "pip-retry.sh: usage: pip-retry.sh <pip-args…>" >&2
  exit 2
fi

for attempt in $(seq 1 "$MAX"); do
  if pip "$@"; then
    exit 0
  fi
  echo "pip-retry.sh: attempt ${attempt}/${MAX} failed: pip $*" >&2
  if [ "$attempt" -eq "$MAX" ]; then
    exit 1
  fi
  sleep "$PAUSE"
done
