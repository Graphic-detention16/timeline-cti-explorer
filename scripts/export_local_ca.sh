#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
target="$project_root/timeline-cti-local-ca.crt"

docker compose -f "$project_root/compose.yaml" cp \
  caddy:/data/caddy/pki/authorities/local/root.crt "$target"
chmod 0644 "$target"
printf 'Local CA exported to %s\n' "$target"

