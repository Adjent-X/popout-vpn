#!/bin/sh
# OpenVPN client-connect — log event + add public IP to verified-clients.
# Env from OpenVPN: common_name, trusted_ip, ifconfig_pool_remote_ip
CLIENT_IP=${trusted_ip:-}
CN=${common_name:-}
VPN_IP=${ifconfig_pool_remote_ip:-}
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

mkdir -p /var/log/openvpn
echo "${TS},connect,${CN},${CLIENT_IP},${VPN_IP}" >> /var/log/openvpn/client-events.log

if [ -z "$CLIENT_IP" ]; then
    exit 1
fi

/usr/bin/sudo /usr/local/sbin/verified-client-add "$CLIENT_IP"
exit 0
