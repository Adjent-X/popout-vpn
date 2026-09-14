#!/usr/bin/env bash
# Install OpenVPN via Angristan before the rest of the Popout stack.
# shellcheck shell=bash

openvpn_is_installed() {
  [[ -f /etc/openvpn/server/server.conf ]] || [[ -f /etc/openvpn/server.conf ]]
}

detect_openvpn_port() {
  local conf=""
  for candidate in /etc/openvpn/server/server.conf /etc/openvpn/server.conf; do
    if [[ -f "$candidate" ]]; then
      conf="$candidate"
      break
    fi
  done
  [[ -n "$conf" ]] || { echo "1194"; return; }
  awk '/^[[:space:]]*port[[:space:]]+/ {print $2; found=1; exit}
       END { if (!found) print 1194 }' "$conf"
}

detect_openvpn_proto() {
  local conf=""
  for candidate in /etc/openvpn/server/server.conf /etc/openvpn/server.conf; do
    if [[ -f "$candidate" ]]; then
      conf="$candidate"
      break
    fi
  done
  [[ -n "$conf" ]] || { echo "udp"; return; }
  awk '/^[[:space:]]*proto[[:space:]]+/ {print $2; found=1; exit}
       END { if (!found) print "udp" }' "$conf" | tr '[:upper:]' '[:lower:]'
}

ensure_openvpn() {
  if openvpn_is_installed; then
    ok "OpenVPN already installed (server.conf present)"
    local proto port
    proto="$(detect_openvpn_proto)"
    port="$(detect_openvpn_port)"
    info "Existing server listens on ${proto}/${port}"
    save_state OVPN_PORT "$port"
    save_state OVPN_PROTO "$proto"
    return
  fi

  info "OpenVPN is not installed. Launching Angristan's openvpn-install.sh"
  echo
  echo "  Popout VPN uses the community OpenVPN installer from"
  echo "  https://github.com/angristan/openvpn-install"
  echo "  (GPL-3.0 — we download and run it; we do not relicense it)."
  echo
  echo "  Complete that wizard first (protocol, port, DNS, first client)."
  echo "  When it finishes, this installer continues with the control plane."
  echo

  local tmp
  tmp="$(mktemp -d)"
  curl -fsSL "${ANGRISTAN_INSTALL_URL}" -o "${tmp}/openvpn-install.sh" \
    || die "Failed to download Angristan openvpn-install.sh"
  chmod +x "${tmp}/openvpn-install.sh"
  bash "${tmp}/openvpn-install.sh"
  rm -rf "$tmp"

  openvpn_is_installed || die "Angristan installer finished but /etc/openvpn/server/server.conf was not found."
  local proto port
  proto="$(detect_openvpn_proto)"
  port="$(detect_openvpn_port)"
  save_state OVPN_PORT "$port"
  save_state OVPN_PROTO "$proto"
  ok "OpenVPN ready (${proto}/${port})"
}

install_openvpn_hooks() {
  mkdir -p /etc/openvpn/server /usr/local/sbin /var/log/openvpn
  if [[ -f "${POPOUT_SRC}/config/openvpn/client-connect.sh" ]]; then
    install -m 755 "${POPOUT_SRC}/config/openvpn/client-connect.sh" /etc/openvpn/server/client-connect.sh
  fi
  if [[ -f "${POPOUT_SRC}/config/openvpn/client-disconnect.sh" ]]; then
    install -m 755 "${POPOUT_SRC}/config/openvpn/client-disconnect.sh" /etc/openvpn/server/client-disconnect.sh
  fi
  if [[ -f "${POPOUT_SRC}/config/openvpn/verified-client-add" ]]; then
    install -m 755 "${POPOUT_SRC}/config/openvpn/verified-client-add" /usr/local/sbin/verified-client-add
  fi
  # visudo snippet so nobody can add verified clients
  if [[ -d /etc/sudoers.d ]]; then
    cat > /etc/sudoers.d/popout-verified-clients <<'EOF'
nobody ALL=(root) NOPASSWD: /usr/local/sbin/verified-client-add
EOF
    chmod 440 /etc/sudoers.d/popout-verified-clients
  fi
}
