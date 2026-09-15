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

# Split the Angristan/Nyr server into concurrent UDP + TCP instances bound to BIND_IP.
configure_dual_openvpn() {
  local src bind udp_port tcp_port
  src=""
  for candidate in /etc/openvpn/server/server.conf /etc/openvpn/server.conf; do
    if [[ -f "$candidate" ]]; then
      src="$candidate"
      break
    fi
  done
  [[ -n "$src" ]] || die "No OpenVPN server.conf to clone into udp/tcp instances"
  bind="${POPOUT_BIND_IP:-10.255.255.1}"
  udp_port="${OVPN_UDP_PORT:-1194}"
  tcp_port="${OVPN_TCP_PORT:-1195}"
  mkdir -p /etc/openvpn/server

  python3 - "$src" "$bind" "$udp_port" "$tcp_port" <<'PY'
import pathlib, re, sys

src, bind, udp_port, tcp_port = sys.argv[1:5]
raw = pathlib.Path(src).read_text(encoding="utf-8", errors="replace")


def rewrite(text: str, *, proto: str, port: str, dev: str, subnet: str, status: str, ipp: str) -> str:
    def set_line(body: str, key: str, value: str) -> str:
        pat = re.compile(rf"(?m)^(?:#\s*)?{re.escape(key)}\s+.*$")
        if pat.search(body):
            return pat.sub(f"{key} {value}", body, count=1)
        return body.rstrip() + f"\n{key} {value}\n"

    body = text
    body = set_line(body, "port", port)
    body = set_line(body, "proto", proto)
    body = set_line(body, "dev", dev)
    body = set_line(body, "server", f"{subnet} 255.255.255.0")
    body = set_line(body, "local", bind)
    body = set_line(body, "status", status)
    body = set_line(body, "ifconfig-pool-persist", ipp)
    if proto.startswith("tcp"):
        body = re.sub(r"(?m)^explicit-exit-notify\s+.*\n?", "", body)
    return body


base = pathlib.Path("/etc/openvpn/server")
udp = rewrite(
    raw,
    proto="udp",
    port=udp_port,
    dev="tun0",
    subnet="10.8.0.0",
    status="/etc/openvpn/server/openvpn-status-udp.log",
    ipp="/etc/openvpn/server/ipp-udp.txt",
)
tcp = rewrite(
    raw,
    proto="tcp",
    port=tcp_port,
    dev="tun1",
    subnet="10.9.0.0",
    status="/etc/openvpn/server/openvpn-status-tcp.log",
    ipp="/etc/openvpn/server/ipp-tcp.txt",
)
(base / "udp.conf").write_text(udp, encoding="utf-8")
(base / "tcp.conf").write_text(tcp, encoding="utf-8")
print("wrote", base / "udp.conf", "and", base / "tcp.conf")
PY

  # Original single instance would clash on port / tun.
  systemctl disable --now openvpn-server@server.service openvpn@server.service 2>/dev/null || true
  systemctl enable --now openvpn-server@udp.service openvpn-server@tcp.service
  save_state OVPN_UDP_PORT "$udp_port"
  save_state OVPN_TCP_PORT "$tcp_port"
  save_state POPOUT_BIND_IP "$bind"
  ok "OpenVPN UDP :${udp_port} and TCP :${tcp_port} bound to ${bind}"
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
