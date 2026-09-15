#!/usr/bin/env bash
# Persistent DNAT + dummy bind IP for Popout VPN servers.
# shellcheck shell=bash

write_dnat_env() {
  load_state
  mkdir -p "${POPOUT_ETC}"
  umask 022
  cat > "${POPOUT_ETC}/dnat.env" <<EOF
BIND_IP=${POPOUT_BIND_IP:-10.255.255.1}
BIND_IFACE=${POPOUT_BIND_IFACE:-popout-bind}
OVPN_UDP_ENABLED=${OVPN_UDP_ENABLED:-1}
OVPN_TCP_ENABLED=${OVPN_TCP_ENABLED:-1}
WG_ENABLED=${WG_ENABLED:-1}
OVPN_UDP_PORT=${OVPN_UDP_PORT:-1194}
OVPN_TCP_PORT=${OVPN_TCP_PORT:-1195}
WG_PORT=${WG_PORT:-51820}
EPHEMERAL_SET=${EPHEMERAL_SET:-ephemeral-ports}
EPHEMERAL_PORT_MIN=${EPHEMERAL_PORT_MIN:-45000}
EPHEMERAL_PORT_MAX=${EPHEMERAL_PORT_MAX:-45099}
EOF
  chmod 644 "${POPOUT_ETC}/dnat.env"
}

install_dnat_forwarding() {
  write_dnat_env
  mkdir -p /etc/modules-load.d
  echo dummy > /etc/modules-load.d/popout-bind.conf
  modprobe dummy 2>/dev/null || true
  install -m 755 "${POPOUT_SRC}/scripts/popout-dnat.sh" /usr/local/sbin/popout-dnat.sh
  cat > /etc/systemd/system/popout-dnat.service <<'EOF'
[Unit]
Description=Popout VPN bind IP + DNAT forwards
DefaultDependencies=no
After=systemd-modules-load.service network-pre.target
Before=network.target openvpn-server@udp.service openvpn-server@tcp.service wg-quick@wg0.service
Wants=network-pre.target

[Service]
Type=oneshot
EnvironmentFile=-/etc/popout-vpn/dnat.env
ExecStart=/usr/local/sbin/popout-dnat.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now popout-dnat.service
  save_state POPOUT_BIND_IP "${POPOUT_BIND_IP:-10.255.255.1}"
  save_state OVPN_UDP_PORT "${OVPN_UDP_PORT:-1194}"
  save_state OVPN_TCP_PORT "${OVPN_TCP_PORT:-1195}"
  ok "DNAT forwards persisted (bind ${POPOUT_BIND_IP:-10.255.255.1})"
}
