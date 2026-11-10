#!/bin/bash
set -e
pnpm install --frozen-lockfile
# HocVu owns its Python schema. Do not push the empty template Drizzle schema:
# it would propose deleting HocVu's tables. Production DDL belongs to Publish.
(
  cd artifacts/hocvu/app
  python manage.py init-storage-schema
  # Leave new tables uninitialized: an operator chooses a new empty store OR
  # an explicitly authorized local-data import. Neither runs unattended.
)
