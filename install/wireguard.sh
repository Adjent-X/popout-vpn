#!/usr/bin/env bash
# Install WireGuard via Angristan, then bind it to the Popout private IP.
# shellcheck shell=bash

wireguard_is_installed() {
  [[ -f /etc/wireguard/params ]] && [[ -f /etc/wireguard/wg0.conf || -n "$(echo /etc/wireguard/*.conf)" ]]
}

detect_wg_port() {
  if [[ -f /etc/wireguard/params ]]; then
    awk -F= '/^SERVER_PORT=/ {print $2; exit}' /etc/wireguard/params
    return
  fi
  echo "${WG_PORT:-51820}"
}

detect_wg_nic() {
  if [[ -f /etc/wireguard/params ]]; then
    awk -F= '/^SERVER_WG_NIC=/ {print $2; exit}' /etc/wireguard/params
    return
  fi
  echo "wg0"
}

ensure_wireguard() {
  if wireguard_is_installed; then
    ok "WireGuard already installed"
    WG_PORT="$(detect_wg_port)"
    save_state WG_PORT "$WG_PORT"
    save_state WG_NIC "$(detect_wg_nic)"
    return
  fi

  info "WireGuard is not installed. Launching Angristan's wireguard-install.sh"
  echo
  echo "  Popout VPN uses the community WireGuard installer from"
  echo "  https://github.com/angristan/wireguard-install"
  echo "  (MIT — we download and run it; we do not relicense it)."
  echo
  echo "  Complete that wizard (interface, subnet, port, DNS, first client)."
  echo "  After it finishes, Popout binds WireGuard to ${POPOUT_BIND_IP:-10.255.255.1}"
  echo "  and publishes it with iptables DNAT."
  echo

  local tmp
  tmp="$(mktemp -d)"
  curl -fsSL "${ANGRISTAN_WG_INSTALL_URL}" -o "${tmp}/wireguard-install.sh" \
    || die "Failed to download Angristan wireguard-install.sh"
  chmod +x "${tmp}/wireguard-install.sh"
  bash "${tmp}/wireguard-install.sh"
  rm -rf "$tmp"

  wireguard_is_installed || die "Angristan WireGuard installer finished but /etc/wireguard/params was not found."
  WG_PORT="$(detect_wg_port)"
  save_state WG_PORT "$WG_PORT"
  save_state WG_NIC "$(detect_wg_nic)"
  ok "WireGuard ready (udp/${WG_PORT})"
}

# Angristan WG listens on 0.0.0.0:PORT. DNAT to BIND_IP still delivers packets
# because the dummy address is local. Keep Angristan's MASQUERADE PostUp.
bind_wireguard_listen() {
  local nic port
  nic="$(detect_wg_nic)"
  port="$(detect_wg_port)"
  [[ -f "/etc/wireguard/${nic}.conf" ]] || return 0
  python3 - "$nic" "$port" <<'PY'
import pathlib, re, sys
nic, port = sys.argv[1], sys.argv[2]
path = pathlib.Path(f"/etc/wireguard/{nic}.conf")
text = path.read_text(encoding="utf-8")
if re.search(r"(?m)^ListenPort\s*=", text):
    text = re.sub(r"(?m)^ListenPort\s*=.*$", f"ListenPort = {port}", text, count=1)
else:
    text = text.replace("[Interface]", f"[Interface]\nListenPort = {port}", 1)
path.write_text(text, encoding="utf-8")
PY
}
