#!/usr/bin/env bash
# Deploy the Popout VPN control plane: env, Mongo user, venv, Next.js, nginx, systemd.
# shellcheck shell=bash

sync_panel_tree() {
  info "Installing panel into ${POPOUT_PANEL_ROOT}"
  mkdir -p "${POPOUT_PANEL_ROOT}"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude 'node_modules/' \
    --exclude '.venv/' \
    --exclude '.next/' \
    --exclude 'logs/' \
    --exclude 'config/app.env' \
    --exclude '__pycache__/' \
    "${POPOUT_SRC}/" "${POPOUT_PANEL_ROOT}/"
  mkdir -p "${POPOUT_PANEL_ROOT}/logs" "${POPOUT_LOG_DIR}"
}

generate_secrets() {
  load_state
  if [[ -z "${JWT_SECRET_KEY:-}" ]]; then
    JWT_SECRET_KEY="$(openssl rand -hex 32)"
  fi
  if [[ -z "${MONGO_PASSWORD:-}" ]]; then
    MONGO_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)"
  fi
  if [[ -z "${ADMIN_EMAIL:-}" ]]; then
    ADMIN_EMAIL="admin@popout.local"
  fi
  if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
    ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | head -c 18)"
  fi
  WAN_IP="$(detect_wan_ip)"
  TUN_IP="$(vpn_tun_ip)"
  TUN_IP="${TUN_IP:-10.8.0.1}"
  OVPN_PORT="${OVPN_PORT:-$(detect_openvpn_port 2>/dev/null || echo 1194)}"
  OVPN_PROTO="${OVPN_PROTO:-$(detect_openvpn_proto 2>/dev/null || echo udp)}"
  load_cloudflare_env 2>/dev/null || true
  if [[ "${CF_ENABLED:-n}" == "y" && -z "${PUBLIC_GATE_PASSWORD:-}" ]]; then
    PUBLIC_GATE_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | head -c 16)"
  fi
  save_state JWT_SECRET_KEY "$JWT_SECRET_KEY"
  save_state MONGO_PASSWORD "$MONGO_PASSWORD"
  save_state ADMIN_EMAIL "$ADMIN_EMAIL"
  save_state ADMIN_PASSWORD "$ADMIN_PASSWORD"
  save_state WAN_IP "$WAN_IP"
  save_state TUN_IP "$TUN_IP"
  if [[ -n "${PUBLIC_GATE_PASSWORD:-}" ]]; then
    save_state PUBLIC_GATE_PASSWORD "$PUBLIC_GATE_PASSWORD"
  fi
}

write_app_env() {
  load_state
  load_cloudflare_env 2>/dev/null || true
  local frontend_url api_url cf_url
  if [[ "${CF_ENABLED:-n}" == "y" && -n "${CF_HOST:-}" ]]; then
    frontend_url="https://${CF_HOST}"
    cf_url="$frontend_url"
    api_url=""
  else
    frontend_url="http://${TUN_IP}"
    cf_url=""
    api_url=""
  fi

  umask 077
  mkdir -p "${POPOUT_PANEL_ROOT}/config"
  cat > "${POPOUT_PANEL_ROOT}/config/app.env" <<EOF
APP_MODE=production
ENVIRONMENT=production
DEBUG=false
APP_VERSION=$(popout_version)
GITHUB_REPO=$(popout_github_slug)

BACKEND_BIND_HOST=127.0.0.1
BACKEND_BIND_PORT=8000
FRONTEND_BIND_HOST=127.0.0.1
FRONTEND_BIND_PORT=3000

PUBLIC_FRONTEND_URL=${frontend_url}
PUBLIC_API_URL=${api_url}
PUBLIC_CLOUDFLARE_FRONTEND_URL=${cf_url}

MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB_NAME=popout_vpn
MONGODB_USER=popout
MONGODB_PASSWORD=${MONGO_PASSWORD}
MONGODB_AUTH_SOURCE=admin

JWT_SECRET_KEY=${JWT_SECRET_KEY}
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

TURNSTILE_ENABLED=false
TURNSTILE_SITE_KEY=
TURNSTILE_SECRET_KEY=
BRAND_NAME=Popout
BRAND_PRODUCT=VPN
SITE_TITLE="Popout VPN Admin"
BRAND_COLOR_BG="#0a0e14"
BRAND_COLOR_PRIMARY="#1e3a8a"
BRAND_COLOR_ACCENT="#06b6d4"
BRAND_COLOR_ACCENT_BRIGHT="#67e8f9"

BOOTSTRAP_ADMIN_EMAIL=${ADMIN_EMAIL}
BOOTSTRAP_ADMIN_PASSWORD=${ADMIN_PASSWORD}
PUBLIC_GATE_PASSWORD=${PUBLIC_GATE_PASSWORD:-}

OPENVPN_FLAVOR=auto
EASYRSA_PATH=/etc/openvpn/server/easy-rsa
EASYRSA_BIN=./easyrsa
OPENVPN_CLIENT_COMMON_PATH=/etc/openvpn/server/client-common.txt
OPENVPN_CA_CERT_PATH=/etc/openvpn/server/ca.crt
OPENVPN_TLS_CRYPT_KEY_PATH=/etc/openvpn/server/tc.key
OPENVPN_TLS_CRYPT_V2_KEY_PATH=
OPENVPN_SERVER_HOST=${WAN_IP:-vpn.example.com}
OPENVPN_SERVER_PORT=${OVPN_UDP_PORT:-${OVPN_PORT:-1194}}
OPENVPN_PROTO=udp
OPENVPN_CRL_PATH=/etc/openvpn/server/crl.pem
OPENVPN_CRL_OWNER=nobody
OPENVPN_CRL_GROUP=nogroup
OPENVPN_STATUS_PATH=/etc/openvpn/server/openvpn-status-udp.log
OPENVPN_IPP_PATH=/etc/openvpn/server/ipp-udp.txt
OPENVPN_CLIENT_EVENTS_PATH=/var/log/openvpn/client-events.log

ATTACK_PCAP_DIR=${POPOUT_LOG_DIR}/captures
ATTACK_EVENTS_DIR=${POPOUT_LOG_DIR}/events
BACKUP_DIR=/root/backups
PANEL_ROOT=${POPOUT_PANEL_ROOT}

APP_NAME="Popout VPN Admin API"
EOF
  chmod 600 "${POPOUT_PANEL_ROOT}/config/app.env"

  # Sync into backend/.env and frontend/.env.local
  grep -v '^#' "${POPOUT_PANEL_ROOT}/config/app.env" | grep -v '^$' \
    > "${POPOUT_PANEL_ROOT}/backend/.env"
  chmod 600 "${POPOUT_PANEL_ROOT}/backend/.env"
  cat > "${POPOUT_PANEL_ROOT}/frontend/.env.local" <<EOF
NEXT_PUBLIC_API_URL=
NEXT_PUBLIC_TURNSTILE_SITE_KEY=
EOF

  cat > "${POPOUT_ETC}/repo.env" <<EOF
POPOUT_GITHUB_SLUG=$(popout_github_slug)
EOF

  umask 077
  cat > "${POPOUT_CRED_FILE}" <<EOF
# Popout VPN first-login credentials — generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Change the password after first login, then delete BOOTSTRAP_ADMIN_PASSWORD
# from ${POPOUT_PANEL_ROOT}/config/app.env
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
PUBLIC_GATE_PASSWORD=${PUBLIC_GATE_PASSWORD:-}
VPN_ADMIN_URL=http://${TUN_IP}/
CLOUDFLARE_ADMIN_URL=${cf_url}
EOF
  chmod 600 "${POPOUT_CRED_FILE}"
  ok "Wrote ${POPOUT_PANEL_ROOT}/config/app.env"
}

setup_mongo_user() {
  load_state
  info "Creating MongoDB user popout…"
  # First start without auth if needed, then create user, then enable auth (template already has it)
  local mongo_cmd=""
  if need_cmd mongosh; then
    mongo_cmd="mongosh"
  elif need_cmd mongo; then
    mongo_cmd="mongo"
  else
    warn "No mongo shell — skip user create (unauthenticated localhost may still work)"
    return
  fi
  # Temporarily allow localhost without auth to create the user if needed
  "$mongo_cmd" --quiet --eval "
    db = db.getSiblingDB('admin');
    try {
      db.createUser({
        user: 'popout',
        pwd: '${MONGO_PASSWORD}',
        roles: [
          { role: 'readWrite', db: 'popout_vpn' },
          { role: 'dbAdmin', db: 'popout_vpn' }
        ]
      });
    } catch (e) {
      if (String(e).indexOf('already exists') === -1 && String(e).indexOf('alreadyHave') === -1) {
        print(e);
      }
    }
  " >/dev/null 2>&1 || warn "Mongo user create skipped (may already exist)"
}

setup_python_backend() {
  info "Python venv + requirements…"
  python3 -m venv "${POPOUT_PANEL_ROOT}/backend/.venv"
  "${POPOUT_PANEL_ROOT}/backend/.venv/bin/pip" install --upgrade pip wheel >/dev/null
  "${POPOUT_PANEL_ROOT}/backend/.venv/bin/pip" install -r "${POPOUT_PANEL_ROOT}/backend/requirements.txt"
  ok "Backend virtualenv ready"
}

setup_frontend_build() {
  info "Installing frontend dependencies and building Next.js (this takes a few minutes)…"
  (
    cd "${POPOUT_PANEL_ROOT}/frontend" || exit
    npm install --no-fund --no-audit
    npm run build
  )
  ok "Frontend production build ready"
}

make_origin_cert() {
  local ssl_dir="/etc/ssl/popout-vpn"
  mkdir -p "$ssl_dir"
  if [[ -f "${ssl_dir}/origin.pem" ]]; then
    ok "Origin certificate already exists"
    return
  fi
  local cn="${CF_HOST:-admin.popout.local}"
  openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes \
    -keyout "${ssl_dir}/origin.key" \
    -out "${ssl_dir}/origin.pem" \
    -subj "/CN=${cn}" \
    -addext "subjectAltName=DNS:${cn},IP:10.8.0.1" >/dev/null 2>&1 \
    || openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes \
         -keyout "${ssl_dir}/origin.key" \
         -out "${ssl_dir}/origin.pem" \
         -subj "/CN=${cn}"
  chmod 600 "${ssl_dir}/origin.key"
  chmod 644 "${ssl_dir}/origin.pem"
  ok "Self-signed origin cert at ${ssl_dir}/origin.pem (Cloudflare SSL Full)"
}

write_nginx() {
  load_state
  load_cloudflare_env 2>/dev/null || true
  local tun="${TUN_IP:-10.8.0.1}"
  mkdir -p /etc/nginx/snippets /etc/nginx/conf.d
  if [[ -f "${POPOUT_SRC}/config/nginx.snippets.cloudflare-realip.conf" ]]; then
    install -m 644 "${POPOUT_SRC}/config/nginx.snippets.cloudflare-realip.conf" \
      /etc/nginx/snippets/popout-cloudflare-realip.conf
  fi

  cat > /etc/nginx/conf.d/popout-vpn.conf <<EOF
# Generated by Popout VPN installer — VPN-only admin + optional public origin
upstream popout_frontend { server 127.0.0.1:3000; keepalive 32; }
upstream popout_backend  { server 127.0.0.1:8000; keepalive 32; }

server {
    listen ${tun}:80 default_server;
    server_name ${tun} admin.vpn.internal _;
    allow 10.8.0.0/24;
    deny all;

    location /api/ {
        proxy_pass http://popout_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
    }
    location / {
        proxy_pass http://popout_frontend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

  if [[ "${CF_ENABLED:-n}" == "y" && -n "${CF_HOST:-}" ]]; then
    cat >> /etc/nginx/conf.d/popout-vpn.conf <<EOF

server {
    listen 80;
    listen [::]:80;
    server_name ${CF_HOST};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${CF_HOST};
    ssl_certificate     /etc/ssl/popout-vpn/origin.pem;
    ssl_certificate_key /etc/ssl/popout-vpn/origin.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    include /etc/nginx/snippets/popout-cloudflare-realip.conf;

    location /api/ {
        proxy_pass http://popout_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
    }
    location / {
        proxy_pass http://popout_frontend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
  fi

  # Disable default site if present
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
  nginx -t
  systemctl enable nginx
  systemctl reload nginx || systemctl restart nginx
  ok "nginx reverse proxy configured"
}

write_systemd_units() {
  cat > /etc/systemd/system/popout-backend.service <<EOF
[Unit]
Description=Popout VPN Admin API (uvicorn)
After=network-online.target mongod.service mongodb.service openvpn-server@server.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${POPOUT_PANEL_ROOT}/backend
EnvironmentFile=-${POPOUT_PANEL_ROOT}/config/app.env
EnvironmentFile=-${POPOUT_PANEL_ROOT}/backend/.env
Environment=PYTHONOPTIMIZE=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
ExecStart=${POPOUT_PANEL_ROOT}/backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --limit-concurrency 64 --timeout-keep-alive 5
Restart=always
RestartSec=3
TimeoutStopSec=25
KillMode=mixed
StandardOutput=append:${POPOUT_PANEL_ROOT}/logs/backend.log
StandardError=append:${POPOUT_PANEL_ROOT}/logs/backend.log

[Install]
WantedBy=multi-user.target
EOF

  cat > /etc/systemd/system/popout-frontend.service <<EOF
[Unit]
Description=Popout VPN Admin frontend (Next.js)
After=network-online.target popout-backend.service
Wants=popout-backend.service

[Service]
Type=simple
WorkingDirectory=${POPOUT_PANEL_ROOT}/frontend
Environment=NODE_ENV=production
Environment=PORT=3000
Environment=HOSTNAME=127.0.0.1
Environment=NODE_OPTIONS=--max-old-space-size=384
ExecStart=/usr/bin/node ./node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3000
Restart=always
RestartSec=3
TimeoutStopSec=25
KillMode=mixed
StandardOutput=append:${POPOUT_PANEL_ROOT}/logs/frontend.log
StandardError=append:${POPOUT_PANEL_ROOT}/logs/frontend.log

[Install]
WantedBy=multi-user.target
EOF

  cat > /etc/systemd/system/popout-attacks.service <<EOF
[Unit]
Description=Popout VPN attack monitor (pps + pcap)
After=network-online.target
Wants=network-online.target
After=openvpn-server@server.service

[Service]
Type=simple
ExecStart=${POPOUT_PANEL_ROOT}/monitor/attacks.sh
Restart=always
RestartSec=5
KillMode=mixed
TimeoutStopSec=20
Environment=POPOUT_ATTACKS_CONF=${POPOUT_ETC}/attacks.conf
Environment=POPOUT_ATTACKS_LOG=${POPOUT_LOG_DIR}/monitor.log
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN CAP_KILL CAP_SETUID CAP_SETGID
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

  chmod 755 "${POPOUT_PANEL_ROOT}/monitor/attacks.sh"
  install -m 644 "${POPOUT_PANEL_ROOT}/monitor/attacks.conf.example" "${POPOUT_ETC}/attacks.conf"
  systemctl daemon-reload
  systemctl enable --now popout-backend.service popout-frontend.service popout-attacks.service
  ok "systemd units enabled"
}

install_cli() {
  install -m 755 "${POPOUT_SRC}/popout-vpn.sh" /usr/local/bin/popout-vpn
  # Keep a copy next to the panel as well
  install -m 755 "${POPOUT_SRC}/popout-vpn.sh" "${POPOUT_PANEL_ROOT}/popout-vpn.sh"
  ok "CLI installed: popout-vpn"
}

maybe_install_shaping() {
  if [[ -f "${POPOUT_SRC}/config/vpn-shape-10.8.sh" ]]; then
    install -m 755 "${POPOUT_SRC}/config/vpn-shape-10.8.sh" /usr/local/sbin/popout-vpn-shape.sh
  fi
}

wait_for_health() {
  info "Waiting for API health…"
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
      ok "API is up"
      return
    fi
    sleep 1
  done
  warn "API did not respond on :8000 yet — check: journalctl -u popout-backend -e"
}

seed_public_gate_into_app() {
  load_state
  [[ -n "${PUBLIC_GATE_PASSWORD:-}" ]] || return 0
  local py="${POPOUT_PANEL_ROOT}/backend/.venv/bin/python"
  [[ -x "$py" ]] || return 0
  info "Enabling public access code on the Cloudflare hostname…"
  (
    cd "${POPOUT_PANEL_ROOT}/backend" || exit
    set -a
    # shellcheck disable=SC1091
    source "${POPOUT_PANEL_ROOT}/config/app.env"
    set +a
    PUBLIC_GATE_PASSWORD="${PUBLIC_GATE_PASSWORD}" "$py" - <<'PY'
import asyncio
import os

from app.core.security import hash_password
from app.db import close_db, connect_db
from app.services.site_settings import get_site_settings, update_site_settings


async def main() -> None:
    pw = (os.environ.get("PUBLIC_GATE_PASSWORD") or "").strip()
    if not pw:
        return
    await connect_db(retries=10, delay_seconds=1.0)
    data, _ = await get_site_settings(use_cache=False)
    if (data.public_gate_password_hash or "").strip():
        if not data.public_gate_enabled:
            await update_site_settings({"public_gate_enabled": True})
        await close_db()
        print("public gate already configured")
        return
    await update_site_settings(
        {
            "public_gate_enabled": True,
            "public_gate_password_hash": hash_password(pw),
        }
    )
    await close_db()
    print("public gate enabled")


asyncio.run(main())
PY
  ) || warn "Could not seed public access code — set it under Server settings after login"
}

deploy_panel_stack() {
  sync_panel_tree
  generate_secrets
  write_app_env
  setup_mongo_user
  setup_python_backend
  setup_frontend_build
  make_origin_cert
  write_nginx
  write_systemd_units
  install_cli
  maybe_install_shaping
  wait_for_health
  seed_public_gate_into_app
}
