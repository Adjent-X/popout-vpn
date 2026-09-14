#!/usr/bin/env bash
# Optional nginx basic-auth helper for a public hostname.
# The panel prefers the in-app public gate modal; this script is a fallback.
# Usage: sync-public-gate.sh <0|1> [password]
set -euo pipefail
echo "popout: in-app public gate is the default; nginx htpasswd sync is a no-op unless you customize this script."
exit 0
