#!/usr/bin/env bash
# Per-client CAKE shaping on OpenVPN tun (10.8.0.0/24).
# Queues over-limit traffic (no hard policer drops) — safer for ICE/STUN/TURN UDP.
# Usage: vpn-shape-10.8.sh [down_mbit] [up_mbit]
# Optional defaults: /etc/default/vpn-shape-10.8 (DOWN_MBIT, UP_MBIT, ENABLED, VPN_IFACE, IFB_DEV)
set -euo pipefail

ENV_FILE="${VPN_SHAPE_ENV:-/etc/default/vpn-shape-10.8}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi

if [[ "${ENABLED:-1}" == "0" ]]; then
  IFACE="${VPN_IFACE:-tun0}"
  IFB_DEV="${IFB_DEV:-ifb0}"
  tc qdisc del dev "$IFACE" root 2>/dev/null || true
  tc qdisc del dev "$IFACE" ingress 2>/dev/null || true
  tc qdisc del dev "$IFB_DEV" root 2>/dev/null || true
  echo "OK: shaping disabled (cleared qdiscs on $IFACE / $IFB_DEV)"
  exit 0
fi

DOWN_MBIT="${1:-${DOWN_MBIT:-23}}"
UP_MBIT="${2:-${UP_MBIT:-23}}"
DOWNLOAD_BW="${DOWN_MBIT}mbit"
UPLOAD_BW="${UP_MBIT}mbit"
IFACE="${VPN_IFACE:-tun0}"
IFB_DEV="${IFB_DEV:-ifb0}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

if ! ip link show "$IFACE" &>/dev/null; then
  echo "Interface $IFACE not found"
  exit 1
fi

command -v tc >/dev/null || { echo "tc missing"; exit 1; }

modprobe ifb numifbs=1 2>/dev/null || modprobe ifb || true
if ! ip link show "$IFB_DEV" &>/dev/null; then
  ip link add "$IFB_DEV" type ifb 2>/dev/null || true
fi
ip link set "$IFB_DEV" up

tc qdisc del dev "$IFACE" root 2>/dev/null || true
tc qdisc del dev "$IFACE" ingress 2>/dev/null || true
tc qdisc del dev "$IFB_DEV" root 2>/dev/null || true

tc qdisc replace dev "$IFACE" root cake bandwidth "$DOWNLOAD_BW" dual-dsthost nat wash

tc qdisc add dev "$IFACE" handle ffff: ingress
tc filter add dev "$IFACE" parent ffff: protocol all u32 match u32 0 0 \
  action mirred egress redirect dev "$IFB_DEV"
tc qdisc replace dev "$IFB_DEV" root cake bandwidth "$UPLOAD_BW" dual-srchost nat wash

echo "OK: $IFACE download=$DOWNLOAD_BW (dual-dsthost)  upload=$UPLOAD_BW via $IFB_DEV (dual-srchost)"
{ tc -s qdisc show dev "$IFACE" || true; } | head -n 8 || true
{ tc -s qdisc show dev "$IFB_DEV" || true; } | head -n 8 || true
exit 0
