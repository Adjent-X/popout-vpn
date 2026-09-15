#!/usr/bin/env bash
# Shared helpers for the Popout VPN installer and CLI.
# shellcheck shell=bash

POPOUT_PANEL_ROOT="${POPOUT_PANEL_ROOT:-/opt/popout-vpn}"
POPOUT_ETC="${POPOUT_ETC:-/etc/popout-vpn}"
POPOUT_LOG_DIR="${POPOUT_LOG_DIR:-/var/log/popout-vpn}"
POPOUT_CRED_FILE="${POPOUT_CRED_FILE:-/root/popout-vpn-credentials.txt}"
POPOUT_STATE="${POPOUT_STATE:-${POPOUT_ETC}/install.state}"
ANGRISTAN_INSTALL_URL="${ANGRISTAN_INSTALL_URL:-https://raw.githubusercontent.com/angristan/openvpn-install/master/openvpn-install.sh}"
ANGRISTAN_WG_INSTALL_URL="${ANGRISTAN_WG_INSTALL_URL:-https://raw.githubusercontent.com/angristan/wireguard-install/master/wireguard-install.sh}"
POPOUT_BIND_IP="${POPOUT_BIND_IP:-10.255.255.1}"
POPOUT_BIND_IFACE="${POPOUT_BIND_IFACE:-popout-bind}"
OVPN_UDP_PORT="${OVPN_UDP_PORT:-1194}"
OVPN_TCP_PORT="${OVPN_TCP_PORT:-1195}"

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'
  C_BLUE=$'\033[34m'
else
  C_RESET="" C_BOLD="" C_DIM="" C_CYAN="" C_GREEN="" C_YELLOW="" C_RED="" C_BLUE=""
fi

die() { echo "${C_RED}ERROR:${C_RESET} $*" >&2; exit 1; }
info() { echo "${C_CYAN}→${C_RESET} $*"; }
ok() { echo "${C_GREEN}✓${C_RESET} $*"; }
warn() { echo "${C_YELLOW}!${C_RESET} $*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

popout_version() {
  local f="${POPOUT_PANEL_ROOT}/VERSION"
  if [[ -f "$f" ]]; then
    head -n1 "$f" | tr -d '\r'
    return
  fi
  if [[ -n "${POPOUT_SRC:-}" && -f "${POPOUT_SRC}/VERSION" ]]; then
    head -n1 "${POPOUT_SRC}/VERSION" | tr -d '\r'
    return
  fi
  echo "0.2.0-beta"
}

popout_github_slug() {
  if [[ -n "${POPOUT_GITHUB_SLUG:-}" ]]; then
    echo "$POPOUT_GITHUB_SLUG"
    return
  fi
  if [[ -f "${POPOUT_ETC}/repo.env" ]]; then
    # shellcheck disable=SC1091
    source "${POPOUT_ETC}/repo.env"
    if [[ -n "${POPOUT_GITHUB_SLUG:-}" ]]; then
      echo "$POPOUT_GITHUB_SLUG"
      return
    fi
  fi
  local remote=""
  if need_cmd git && [[ -d "${POPOUT_PANEL_ROOT}/.git" ]]; then
    remote="$(git -C "${POPOUT_PANEL_ROOT}" remote get-url origin 2>/dev/null || true)"
  fi
  if [[ -n "$remote" ]]; then
    remote="${remote%.git}"
    remote="${remote#git@github.com:}"
    remote="${remote#https://github.com/}"
    echo "$remote"
    return
  fi
  echo "Adjent-X/popout-vpn"
}

popout_github_url() {
  echo "https://github.com/$(popout_github_slug)"
}

_ask_tty() {
  local prompt="$1"
  local reply=""
  if [[ -t 0 ]]; then
    read -r -p "$prompt" reply
  elif [[ -r /dev/tty ]]; then
    read -r -p "$prompt" reply </dev/tty
  else
    die "No TTY available for interactive prompt. Download install.sh and run it with sudo."
  fi
  printf '%s' "$reply"
}

ask() {
  local prompt="$1"
  local default="${2:-}"
  local reply
  if [[ -n "$default" ]]; then
    reply="$(_ask_tty "${prompt} [${default}]: ")"
    echo "${reply:-$default}"
  else
    reply="$(_ask_tty "${prompt}: ")"
    echo "$reply"
  fi
}

ask_secret() {
  local prompt="$1"
  local reply=""
  if [[ -t 0 ]]; then
    read -r -s -p "$prompt" reply
    echo >/dev/tty 2>/dev/null || echo
  elif [[ -r /dev/tty ]]; then
    read -r -s -p "$prompt" reply </dev/tty
    echo >/dev/tty
  else
    die "No TTY available for a secret prompt."
  fi
  printf '%s' "$reply"
}

ask_yn() {
  local prompt="$1"
  local default="${2:-n}"
  local reply
  while true; do
    reply="$(_ask_tty "${prompt} ")"
    reply="${reply:-$default}"
    case "$reply" in
      y|Y|yes|YES) echo "y"; return ;;
      n|N|no|NO) echo "n"; return ;;
    esac
    echo "Please answer y or n."
  done
}

detect_wan_ip() {
  local ip=""
  ip="$(curl -4 -fsS --max-time 8 https://ifconfig.co 2>/dev/null || true)"
  ip="${ip%%$'\n'*}"
  if [[ ! "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    ip="$(curl -4 -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
  fi
  echo "${ip%%$'\n'*}"
}

detect_wan_iface() {
  local iface=""
  iface="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"
  echo "${iface:-eth0}"
}

vpn_tun_ip() {
  if ip link show tun0 >/dev/null 2>&1; then
    ip -4 -o addr show tun0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1
  fi
}

ensure_dirs() {
  mkdir -p "${POPOUT_PANEL_ROOT}" "${POPOUT_ETC}" "${POPOUT_LOG_DIR}" \
    "${POPOUT_LOG_DIR}/captures" "${POPOUT_LOG_DIR}/events" \
    /etc/iptables /root/backups
}

save_state() {
  local key="$1"
  local value="$2"
  mkdir -p "${POPOUT_ETC}"
  touch "${POPOUT_STATE}"
  chmod 600 "${POPOUT_STATE}"
  if grep -q "^${key}=" "${POPOUT_STATE}" 2>/dev/null; then
    # portable in-place replace
    local tmp
    tmp="$(mktemp)"
    awk -F= -v k="$key" -v v="$value" '
      BEGIN { OFS="=" }
      $1==k { print k, v; next }
      { print }
    ' "${POPOUT_STATE}" >"$tmp"
    mv "$tmp" "${POPOUT_STATE}"
  else
    printf '%s=%s\n' "$key" "$value" >>"${POPOUT_STATE}"
  fi
}

load_state() {
  if [[ -f "${POPOUT_STATE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    # shellcheck source=/dev/null
    source "${POPOUT_STATE}"
    set +a
  fi
}

mask_secret() {
  local v="$1"
  local n=${#v}
  if (( n <= 4 )); then
    echo "****"
    return
  fi
  echo "${v:0:2}****${v: -2}"
}
