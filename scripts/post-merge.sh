#!/bin/bash
# Runs automatically after a task merge on Replit. Must be idempotent and
# non-interactive.
set -euo pipefail

# Install any Python dependencies added by the merged work.
# The hook may run without Replit's pip config, so pass its settings explicitly:
# packages live in the workspace user site (.pythonlibs), not the Nix store.
export PYTHONUSERBASE="${PYTHONUSERBASE:-$PWD/.pythonlibs}"
python -m pip install --quiet --disable-pip-version-check \
  --user --break-system-packages -r requirements.txt

# Rebuild the search index so merged retrieval/document changes take effect.
# Uploaded documents are kept; only the derived index is regenerated.
HV_SEMANTIC="${HV_SEMANTIC:-0}" python manage.py ingest
