#!/usr/bin/env bash
set -euo pipefail

# Install the monorepo dependencies after a Replit merge.
pnpm install --frozen-lockfile

# HocVu owns its Python schema. Do not push the empty template Drizzle schema:
# it would propose deleting HocVu's tables. Production DDL belongs to Publish.
# Create only the development schema; leave store initialization/import explicit.
(
  cd artifacts/hocvu/app
  python manage.py init-storage-schema
)
