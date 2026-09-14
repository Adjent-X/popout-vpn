#!/bin/bash
# Install Cloudflare eth0 HTTP/HTTPS allowlist — never touches NAT / VPN rules.
set -euo pipefail

install -d -m 755 /usr/local/sbin /etc/nftables.d /root/nft-backups
install -m 755 /tmp/update-cloudflare-nft-set.sh /usr/local/sbin/update-cloudflare-nft-set.sh
install -m 644 /tmp/nftables-cloudflare-wan.conf /etc/nftables.d/cloudflare-wan.nft

nft list table ip nat >"/root/nft-backups/ip-nat-$(date +%Y%m%d%H%M%S).nft" || true
iptables-save -t nat >"/root/nft-backups/iptables-nat-$(date +%Y%m%d%H%M%S).v4" || true

cat > /etc/nftables.conf <<'EOF'
#!/usr/sbin/nft -f
# Do not flush ruleset — VPN NAT lives in table ip nat.
include "/etc/nftables.d/cloudflare-wan.nft"
EOF
chmod 644 /etc/nftables.conf

# Replace only inet raw (Bullseye nft has no "destroy table")
nft delete table inet raw 2>/dev/null || true
nft -f /etc/nftables.d/cloudflare-wan.nft
/usr/local/sbin/update-cloudflare-nft-set.sh

# Sanity: NAT must still exist
nft list table ip nat | grep -q masquerade
iptables -t nat -S | grep -q MASQUERADE

# Strip legacy iptables :80/:443 CF/raw rules only (not nat)
while iptables -t raw -C PREROUTING -i eth0 -p tcp -m multiport --dports 80,443 -m tcp --tcp-flags FIN,SYN,RST,ACK SYN -j ACCEPT 2>/dev/null; do
  iptables -t raw -D PREROUTING -i eth0 -p tcp -m multiport --dports 80,443 -m tcp --tcp-flags FIN,SYN,RST,ACK SYN -j ACCEPT || true
done
while iptables -t raw -C PREROUTING -i eth0 -p tcp -m multiport --dports 80,443 -m set ! --match-set cloudflare_v4 src -j DROP 2>/dev/null; do
  iptables -t raw -D PREROUTING -i eth0 -p tcp -m multiport --dports 80,443 -m set ! --match-set cloudflare_v4 src -j DROP || true
done
while iptables -t raw -C PREROUTING -i eth0 -p tcp -m multiport --dports 80,443 -m set ! --match-set cloudflare-ipv4 src -j DROP 2>/dev/null; do
  iptables -t raw -D PREROUTING -i eth0 -p tcp -m multiport --dports 80,443 -m set ! --match-set cloudflare-ipv4 src -j DROP || true
done
while iptables -C INPUT -p tcp -m multiport --dports 80,443 -m set ! --match-set cloudflare-ipv4 src -m conntrack --ctstate NEW -j DROP 2>/dev/null; do
  iptables -D INPUT -p tcp -m multiport --dports 80,443 -m set ! --match-set cloudflare-ipv4 src -m conntrack --ctstate NEW -j DROP || true
done
while iptables -C INPUT -p tcp -m multiport --dports 80,443 -m set ! --match-set cloudflare_v4 src -m conntrack --ctstate NEW -j DROP 2>/dev/null; do
  iptables -D INPUT -p tcp -m multiport --dports 80,443 -m set ! --match-set cloudflare_v4 src -m conntrack --ctstate NEW -j DROP || true
done
iptables-save > /etc/iptables/rules.v4 2>/dev/null || true

cat > /etc/cron.d/cloudflare-nft-set <<'EOF'
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
17 */6 * * * root /usr/local/sbin/update-cloudflare-nft-set.sh >>/var/log/cloudflare-nft-set.log 2>&1
EOF
chmod 644 /etc/cron.d/cloudflare-nft-set

mkdir -p /etc/systemd/system/nftables.service.d
cat > /etc/systemd/system/nftables.service.d/cloudflare-set.conf <<'EOF'
[Service]
ExecStartPost=/usr/local/sbin/update-cloudflare-nft-set.sh
EOF
systemctl daemon-reload
systemctl enable nftables

echo "NAT OK"; iptables -t nat -S | grep -E 'MASQUERADE|DNAT'
echo "RAW OK"; nft list chain inet raw prerouting
echo DONE
