#!/bin/bash
# Refresh nftables Cloudflare IPv4 set from https://www.cloudflare.com/ips-v4
# Only updates set elements — never flushes NAT or other tables.
set -euo pipefail

SET_FAMILY="inet"
SET_TABLE="raw"
SET_NAME="cloudflare_v4"
URL_V4="https://www.cloudflare.com/ips-v4"
LOCK="/run/update-cloudflare-nft-set.lock"
TMP="$(mktemp)"
NFT_TMP="$(mktemp)"

cleanup() {
  rm -f "$TMP" "$NFT_TMP"
}
trap cleanup EXIT

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "another update is running" >&2
  exit 0
fi

if ! nft list set "${SET_FAMILY}" "${SET_TABLE}" "${SET_NAME}" >/dev/null 2>&1; then
  # Recreate only our table (never flush ruleset)
  if [[ -f /etc/nftables.d/cloudflare-wan.nft ]]; then
    nft -f /etc/nftables.d/cloudflare-wan.nft
  elif [[ -f /etc/nftables.conf ]] && grep -q 'cloudflare_v4' /etc/nftables.conf; then
    nft -f /etc/nftables.conf
  else
    echo "nft set ${SET_FAMILY} ${SET_TABLE} ${SET_NAME} missing" >&2
    exit 1
  fi
fi

curl -fsSL --max-time 30 "$URL_V4" -o "$TMP"

count=0
{
  echo "flush set ${SET_FAMILY} ${SET_TABLE} ${SET_NAME}"
  echo "add element ${SET_FAMILY} ${SET_TABLE} ${SET_NAME} {"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="${line//[[:space:]]/}"
    [[ -z "$line" ]] && continue
    if [[ ! "$line" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]]; then
      echo "invalid Cloudflare prefix: $line" >&2
      exit 1
    fi
    echo "  $line,"
    count=$((count + 1))
  done <"$TMP"
  echo "}"
} >"$NFT_TMP"

if [[ "$count" -lt 5 ]]; then
  echo "refusing update: only $count prefixes from $URL_V4" >&2
  exit 1
fi

nft -f "$NFT_TMP"
echo "cloudflare_v4 updated: $count prefixes"
