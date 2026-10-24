#!/usr/bin/env bash
# Thin wrapper: the build and start scripts live in deploy/scripts.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy/scripts/start.sh" "$@"
