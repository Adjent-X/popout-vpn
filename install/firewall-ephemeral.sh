#!/usr/bin/env bash
# Multiport / port-knock helper: ipset ephemeral-ports + NAT REDIRECT to OpenVPN.
# shellcheck shell=bash

EPHEMERAL_SET="${EPHEMERAL_SET:-ephemeral-ports}"
EPHEMERAL_PORT_MIN="${EPHEMERAL_PORT_MIN:-45000}"
EPHEMERAL_PORT_MAX="${EPHEMERAL_PORT_MAX:-45099}"

detect_openvpn_port_safe() {
  if need_cmd detect_openvpn_port; then
    detect_openvpn_port
  else
    awk '/^[[:space:]]*port[[:space:]]+/ {print $2; found=1; exit}
         END { if (!found) print 1194 }' /etc/openvpn/server/server.conf 2>/dev/null || echo 1194
  fi
}

detect_openvpn_proto_safe() {
  if need_cmd detect_openvpn_proto; then
    detect_openvpn_proto
  else
    awk '/^[[:space:]]*proto[[:space:]]+/ {print $2; found=1; exit}
         END { if (!found) print "udp" }' /etc/openvpn/server/server.conf 2>/dev/null \
      | tr '[:upper:]' '[:lower:]' || echo udp
  fi
}

setup_ephemeral_ports() {
  need_cmd ipset || die "ipset is required for ephemeral-ports"
  need_cmd iptables || die "iptables is required for NAT REDIRECT"

  local ovpn_port ovpn_proto
  if declare -F detect_openvpn_port >/dev/null; then
    ovpn_port="$(detect_openvpn_port)"
    ovpn_proto="$(detect_openvpn_proto)"
  else
    ovpn_port="$(detect_openvpn_port_safe)"
    ovpn_proto="$(detect_openvpn_proto_safe)"
  fi
  ovpn_port="${ovpn_port:-1194}"
  ovpn_proto="${ovpn_proto:-udp}"
  case "$ovpn_proto" in
    tcp*) ovpn_proto="tcp" ;;
    *) ovpn_proto="udp" ;;
  esac

  info "Initializing ipset ${EPHEMERAL_SET} (${EPHEMERAL_PORT_MIN}-${EPHEMERAL_PORT_MAX}) → REDIRECT ${ovpn_proto}/${ovpn_port}"

  ipset create "${EPHEMERAL_SET}" bitmap:port range 0-65535 -exist
  # bitmap:port supports adding a range as from-to on recent ipset
  if ! ipset add "${EPHEMERAL_SET}" "${EPHEMERAL_PORT_MIN}-${EPHEMERAL_PORT_MAX}" -exist 2>/dev/null; then
    local p
    for p in $(seq "${EPHEMERAL_PORT_MIN}" "${EPHEMERAL_PORT_MAX}"); do
      ipset add "${EPHEMERAL_SET}" "$p" -exist
    done
  fi

  # Idempotent NAT REDIRECT for both TCP and UDP so remote-random clients work
  # regardless of which protocol the .ovpn lists.
  _ensure_redirect tcp "$ovpn_port"
  _ensure_redirect udp "$ovpn_port"

  mkdir -p /etc/iptables
  ipset save > /etc/iptables/ipsets
  if need_cmd iptables-save; then
    iptables-save > /etc/iptables/rules.v4
  fi

  install_ephemeral_units "$ovpn_port"

  save_state EPHEMERAL_SET "$EPHEMERAL_SET"
  save_state EPHEMERAL_PORT_MIN "$EPHEMERAL_PORT_MIN"
  save_state EPHEMERAL_PORT_MAX "$EPHEMERAL_PORT_MAX"
  save_state OVPN_PORT "$ovpn_port"
  ok "ephemeral-ports ipset + NAT REDIRECT → ${ovpn_port}"
}

_ensure_redirect() {
  local proto="$1"
  local dest="$2"
  if iptables -t nat -C PREROUTING -p "$proto" -m set --match-set "${EPHEMERAL_SET}" dst \
      -j REDIRECT --to-ports "$dest" 2>/dev/null; then
    return
  fi
  iptables -t nat -A PREROUTING -p "$proto" -m set --match-set "${EPHEMERAL_SET}" dst \
    -j REDIRECT --to-ports "$dest"
}

install_ephemeral_units() {
  local dest="$1"
  cat > /usr/local/sbin/popout-ephemeral-ports.sh <<EOF
#!/usr/bin/env bash
set -euo pipefail
SET="${EPHEMERAL_SET}"
MIN="${EPHEMERAL_PORT_MIN}"
MAX="${EPHEMERAL_PORT_MAX}"
DEST="${dest}"
ipset create "\$SET" bitmap:port range 0-65535 -exist
if ! ipset add "\$SET" "\$MIN-\$MAX" -exist 2>/dev/null; then
  for p in \$(seq "\$MIN" "\$MAX"); do ipset add "\$SET" "\$p" -exist; done
fi
if [[ -f /etc/iptables/ipsets ]]; then
  ipset restore -exist < /etc/iptables/ipsets || true
fi
for proto in tcp udp; do
  iptables -t nat -C PREROUTING -p "\$proto" -m set --match-set "\$SET" dst -j REDIRECT --to-ports "\$DEST" 2>/dev/null \\
    || iptables -t nat -A PREROUTING -p "\$proto" -m set --match-set "\$SET" dst -j REDIRECT --to-ports "\$DEST"
done
ipset save > /etc/iptables/ipsets
EOF
  chmod 755 /usr/local/sbin/popout-ephemeral-ports.sh

  cat > /etc/systemd/system/popout-ephemeral-ports.service <<'EOF'
[Unit]
Description=Popout VPN ephemeral-ports ipset + NAT REDIRECT
DefaultDependencies=no
After=network-pre.target
Before=network.target openvpn-server@server.service
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/popout-ephemeral-ports.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

  cat > /etc/systemd/system/ipset-restore.service <<'EOF'
[Unit]
Description=Restore ipset sets from /etc/iptables/ipsets
DefaultDependencies=no
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'test -f /etc/iptables/ipsets && ipset restore -exist < /etc/iptables/ipsets || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now ipset-restore.service popout-ephemeral-ports.service
}
