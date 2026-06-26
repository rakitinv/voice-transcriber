#!/usr/bin/env bash
# Install PyTorch CPU or CUDA wheels after `poetry install`.
# Used by docker/Dockerfile.ml-base (canonical); child Dockerfiles inherit torch from ml-base.
#
# Usage:
#   install-torch.sh cpu
#   install-torch.sh cuda
#   TORCH_VARIANT=cuda TORCH_VERSION=2.10.0 install-torch.sh
#
set -euo pipefail

VARIANT="${TORCH_VARIANT:-${1:-cpu}}"
VERSION="${TORCH_VERSION:-2.10.0}"

case "${VARIANT}" in
  cuda|gpu)
    INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"
    SUFFIX="+cu128"
    ;;
  cpu)
    INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
    SUFFIX="+cpu"
    ;;
  *)
    echo "install-torch.sh: unknown variant '${VARIANT}' (use cpu or cuda)" >&2
    exit 1
    ;;
esac

echo "install-torch.sh: torch==${VERSION}${SUFFIX} from ${INDEX_URL}"
pip-retry.sh install --force-reinstall \
  "torch==${VERSION}${SUFFIX}" \
  "torchaudio==${VERSION}${SUFFIX}" \
  --index-url "${INDEX_URL}"
