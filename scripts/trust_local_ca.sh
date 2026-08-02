#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
certificate="$project_root/timeline-cti-local-ca.crt"

if [ ! -f "$certificate" ]; then
  "$project_root/scripts/export_local_ca.sh"
fi

case "$(uname -s)" in
  Linux)
    if command -v update-ca-certificates >/dev/null 2>&1; then
      sudo install -m 0644 "$certificate" /usr/local/share/ca-certificates/timeline-cti-local-ca.crt
      sudo update-ca-certificates
    else
      printf 'Import %s into your operating system and browser trust store.\n' "$certificate"
    fi
    ;;
  Darwin)
    sudo security add-trusted-cert -d -r trustRoot \
      -k /Library/Keychains/System.keychain "$certificate"
    ;;
  *)
    printf 'Import %s into your operating system and browser trust store.\n' "$certificate"
    ;;
esac

