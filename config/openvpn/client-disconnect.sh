#!/bin/sh
# OpenVPN client-disconnect — log only (keep verified-clients membership).
CN=${common_name:-}
CLIENT_IP=${trusted_ip:-}
VPN_IP=${ifconfig_pool_remote_ip:-}
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p /var/log/openvpn
echo "${TS},disconnect,${CN},${CLIENT_IP},${VPN_IP}" >> /var/log/openvpn/client-events.log
exit 0
