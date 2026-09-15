#!/usr/bin/env bash
# Optional Cloudflare: prompt, then auto-tune the zone for the admin portal.
# The OpenVPN tunnel is NEVER proxied — only the web UI.
# shellcheck shell=bash

CF_API="${CF_API:-https://api.cloudflare.com/client/v4}"

cf_auth_args() {
  # Uses CF_TOKEN (API token) or CF_EMAIL + CF_GLOBAL_KEY
  if [[ -n "${CF_TOKEN:-}" ]]; then
    echo "-H" "Authorization: Bearer ${CF_TOKEN}"
    return
  fi
  if [[ -n "${CF_EMAIL:-}" && -n "${CF_GLOBAL_KEY:-}" ]]; then
    echo "-H" "X-Auth-Email: ${CF_EMAIL}" "-H" "X-Auth-Key: ${CF_GLOBAL_KEY}"
    return
  fi
  die "Cloudflare credentials missing"
}

cf_curl() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local args=()
  # shellcheck disable=SC2207
  args+=($(cf_auth_args))
  if [[ -n "$data" ]]; then
    curl -fsS -X "$method" "${CF_API}${path}" \
      "${args[@]}" \
      -H "Content-Type: application/json" \
      --data "$data"
  else
    curl -fsS -X "$method" "${CF_API}${path}" \
      "${args[@]}" \
      -H "Content-Type: application/json"
  fi
}

prompt_cloudflare() {
  echo
  echo "${C_BOLD}Cloudflare (admin portal only)${C_RESET}"
  echo "  Orange-cloud DNS for the web UI, WAF, and cache rules."
  echo "  OpenVPN itself stays direct to this server — Cloudflare cannot proxy the tunnel."
  echo
  local yn
  yn="$(ask_yn "Put the admin portal behind Cloudflare? [y/N]" "n")"
  if [[ "$yn" != "y" ]]; then
    CF_ENABLED=n
    save_state CF_ENABLED n
    ok "Skipping Cloudflare — VPN-only admin on the tunnel IP"
    return
  fi
  CF_ENABLED=y
  CF_DOMAIN="$(ask "Apex domain in Cloudflare (example.com)")"
  [[ -n "$CF_DOMAIN" ]] || die "Domain is required when Cloudflare is enabled"
  CF_HOST="$(ask "Admin hostname" "admin.${CF_DOMAIN}")"
  echo
  echo "  Create an API token at https://dash.cloudflare.com/profile/api-tokens"
  echo "  with Zone permissions (see docs/CLOUDFLARE.md):"
  echo "    DNS Edit, Zone Settings Edit, Zone Read, Cache Purge,"
  echo "    Firewall Services Edit, Cache Rules Edit (or Account Filter Lists)."
  echo "  A Global API Key + account email also works (legacy zone API key)."
  echo
  local kind
  kind="$(ask "Credential type: token or key? [token/key]" "token")"
  case "$kind" in
    key|global|api-key|apikey)
      CF_EMAIL="$(ask "Cloudflare account email")"
      CF_GLOBAL_KEY="$(ask_secret "Cloudflare Global API Key: ")"
      echo
      [[ -n "$CF_EMAIL" && -n "$CF_GLOBAL_KEY" ]] || die "Email and Global API Key are required"
      CF_TOKEN=""
      ;;
    *)
      CF_TOKEN="$(ask_secret "Cloudflare API token: ")"
      echo
      [[ -n "$CF_TOKEN" ]] || die "API token is required"
      CF_EMAIL=""
      CF_GLOBAL_KEY=""
      ;;
  esac
  save_state CF_ENABLED y
  save_state CF_DOMAIN "$CF_DOMAIN"
  save_state CF_HOST "$CF_HOST"
  # Store secrets in a 600 file, not in the world-readable state dump if we can avoid it
  umask 077
  cat > "${POPOUT_ETC}/cloudflare.env" <<EOF
CF_ENABLED=y
CF_DOMAIN=$(printf '%q' "$CF_DOMAIN")
CF_HOST=$(printf '%q' "$CF_HOST")
CF_TOKEN=$(printf '%q' "${CF_TOKEN}")
CF_EMAIL=$(printf '%q' "${CF_EMAIL}")
CF_GLOBAL_KEY=$(printf '%q' "${CF_GLOBAL_KEY}")
EOF
  chmod 600 "${POPOUT_ETC}/cloudflare.env"
  ok "Cloudflare credentials stored in ${POPOUT_ETC}/cloudflare.env"
}

load_cloudflare_env() {
  CF_ENABLED="${CF_ENABLED:-n}"
  if [[ -f "${POPOUT_ETC}/cloudflare.env" ]]; then
    # shellcheck disable=SC1091
    source "${POPOUT_ETC}/cloudflare.env"
  fi
}

resolve_cf_zone_id() {
  local domain="$1"
  local json
  json="$(cf_curl GET "/zones?name=${domain}&per_page=50")"
  printf '%s' "$json" | python3 -c "
import json,sys
data=json.load(sys.stdin)
zones=data.get('result') or []
want='${domain}'.lower()
for z in zones:
    if str(z.get('name','')).lower()==want:
        print(z.get('id',''))
        raise SystemExit
if zones:
    print(zones[0].get('id',''))
"
}

apply_cloudflare_zone() {
  load_cloudflare_env
  [[ "${CF_ENABLED:-n}" == "y" ]] || { info "Cloudflare disabled — no zone changes"; return; }
  need_cmd curl || die "curl is required for Cloudflare API calls"
  need_cmd python3 || die "python3 is required to parse Cloudflare API JSON"

  local wan_ip wan6
  wan_ip="$(detect_wan_ip)"
  [[ -n "$wan_ip" ]] || die "Could not detect public IPv4 for the Cloudflare A record"
  wan6="$(curl -6 -fsS --max-time 6 https://ifconfig.co 2>/dev/null || true)"
  wan6="${wan6%%$'\n'*}"

  info "Resolving Cloudflare zone for ${CF_DOMAIN}…"
  CF_ZONE_ID="$(resolve_cf_zone_id "$CF_DOMAIN")"
  [[ -n "$CF_ZONE_ID" ]] || die "Could not find a Cloudflare zone named ${CF_DOMAIN}. Check the token permissions and domain."
  save_state CF_ZONE_ID "$CF_ZONE_ID"
  ok "Zone id ${CF_ZONE_ID}"

  info "Creating proxied DNS for ${CF_HOST} → ${wan_ip}"
  _cf_upsert_dns A "$CF_HOST" "$wan_ip"
  if [[ -n "$wan6" && "$wan6" == *:* ]]; then
    _cf_upsert_dns AAAA "$CF_HOST" "$wan6"
  fi

  info "Tuning SSL, HTTPS, HTTP/3, Brotli, security…"
  _cf_patch_setting ssl full
  _cf_patch_setting always_use_https on
  _cf_patch_setting min_tls_version 1.2
  _cf_patch_setting tls_1_3 on
  _cf_patch_setting brotli on
  _cf_patch_setting http3 on
  _cf_patch_setting opportunistic_encryption on
  _cf_patch_setting security_level medium
  _cf_patch_setting browser_check on
  _cf_patch_setting email_obfuscation on
  _cf_patch_setting rocket_loader off
  _cf_patch_setting websockets on
  _cf_patch_setting browser_cache_ttl 0

  info "Installing cache rules (bypass /api and dashboard, cache /_next/static)…"
  _cf_put_cache_rules "$CF_HOST"

  ok "Cloudflare zone tuned for ${CF_HOST}"
  echo "  SSL mode: Full (self-signed origin cert is OK)."
  echo "  Switch to Full (strict) later with a Cloudflare Origin CA if you want."
}

_cf_patch_setting() {
  local name="$1"
  local value="$2"
  local payload
  payload="$(VALUE="$value" python3 -c 'import json,os; v=os.environ["VALUE"]; print(json.dumps({"value": int(v) if v.isdigit() else v}))')"
  cf_curl PATCH "/zones/${CF_ZONE_ID}/settings/${name}" "$payload" >/dev/null \
    || warn "Could not set ${name}=${value} (token may lack Zone Settings Edit)"
}

_cf_upsert_dns() {
  local rtype="$1"
  local name="$2"
  local content="$3"
  local list payload rec_id
  list="$(cf_curl GET "/zones/${CF_ZONE_ID}/dns_records?type=${rtype}&name=${name}")"
  rec_id="$(printf '%s' "$list" | python3 -c "import json,sys; r=(json.load(sys.stdin).get('result') or []); print(r[0]['id'] if r else '')")"
  payload="$(python3 -c "import json; print(json.dumps({'type':'$rtype','name':'$name','content':'$content','ttl':1,'proxied':True,'comment':'Popout VPN admin portal'}))")"
  if [[ -n "$rec_id" ]]; then
    cf_curl PUT "/zones/${CF_ZONE_ID}/dns_records/${rec_id}" "$payload" >/dev/null
  else
    cf_curl POST "/zones/${CF_ZONE_ID}/dns_records" "$payload" >/dev/null
  fi
}

_cf_put_cache_rules() {
  local host="$1"
  local payload
  payload="$(HOST="$host" python3 - <<'PY'
import json, os
host = os.environ["HOST"]
host_expr = f'http.host eq "{host}"'
rules = [
    {
        "action": "set_cache_settings",
        "description": "Popout: bypass cache for app and API",
        "enabled": True,
        "expression": (
            f"({host_expr}) and ("
            'starts_with(http.request.uri.path, "/api/") or '
            'http.request.uri.path eq "/login" or '
            'starts_with(http.request.uri.path, "/login/") or '
            'http.request.uri.path eq "/register" or '
            'starts_with(http.request.uri.path, "/register/") or '
            'starts_with(http.request.uri.path, "/dashboard")'
            ")"
        ),
        "action_parameters": {"cache": False},
    },
    {
        "action": "set_cache_settings",
        "description": "Popout: cache Next.js static assets",
        "enabled": True,
        "expression": f'({host_expr}) and starts_with(http.request.uri.path, "/_next/static/")',
        "action_parameters": {
            "cache": True,
            "edge_ttl": {"mode": "override_origin", "default": 2678400},
            "browser_ttl": {"mode": "override_origin", "default": 2678400},
        },
    },
]
print(json.dumps({"rules": rules}))
PY
)"
  cf_curl PUT "/zones/${CF_ZONE_ID}/rulesets/phases/http_request_cache_settings/entrypoint" "$payload" >/dev/null \
    || warn "Cache Rules API failed — your plan/token may not include Cache Rules Edit"
}

seed_cloudflare_into_app() {
  load_cloudflare_env
  [[ "${CF_ENABLED:-n}" == "y" ]] || return 0
  [[ -x "${POPOUT_PANEL_ROOT}/backend/.venv/bin/python" ]] || return 0
  info "Seeding Cloudflare token into panel site settings…"
  (
    cd "${POPOUT_PANEL_ROOT}/backend"
    # shellcheck disable=SC1091
    set -a
    [[ -f "${POPOUT_PANEL_ROOT}/config/app.env" ]] && source "${POPOUT_PANEL_ROOT}/config/app.env"
    set +a
    CF_TOKEN="${CF_TOKEN:-}" CF_ZONE_ID="${CF_ZONE_ID:-}" CF_HOST="${CF_HOST:-}" \
      .venv/bin/python - <<'PY'
import os, asyncio
from app.db import connect_db, get_db, close_db
from app.services.site_settings import update_site_settings
from app.services.cloudflare_waf import sync_cloudflare_waf

async def main():
    await connect_db(retries=10, delay_seconds=1.0)
    await update_site_settings({
        "cloudflare_api_token": os.environ.get("CF_TOKEN") or "",
        "cloudflare_zone_id": os.environ.get("CF_ZONE_ID") or "",
        "cloudflare_waf_sync_enabled": True,
        "cloudflare_waf_hosts": os.environ.get("CF_HOST") or "",
    })
    try:
        result = await sync_cloudflare_waf(force=True)
        print("WAF sync:", result)
    except Exception as exc:
        print("WAF sync skipped:", exc)
    await close_db()

asyncio.run(main())
PY
  ) || warn "Could not seed Cloudflare into Mongo — set it under Server settings after login"
}

maybe_install_cf_nft() {
  load_cloudflare_env
  [[ "${CF_ENABLED:-n}" == "y" ]] || return 0
  local wan
  wan="$(detect_wan_iface)"
  if [[ -f "${POPOUT_SRC}/scripts/nftables-cloudflare-wan.conf" ]]; then
    info "Optional: restricting WAN :80/:443 to Cloudflare IPs on ${wan}"
    local yn
    yn="$(ask_yn "Lock origin HTTP/HTTPS to Cloudflare ranges only? [y/N]" "n")"
    [[ "$yn" == "y" ]] || return 0
    install -d -m 755 /usr/local/sbin /etc/nftables.d
    sed "s/\"eth0\"/\"${wan}\"/g" "${POPOUT_SRC}/scripts/nftables-cloudflare-wan.conf" \
      > /etc/nftables.d/cloudflare-wan.nft
    install -m 755 "${POPOUT_SRC}/scripts/update-cloudflare-nft-set.sh" /usr/local/sbin/update-cloudflare-nft-set.sh
    nft delete table inet raw 2>/dev/null || true
    nft -f /etc/nftables.d/cloudflare-wan.nft
    /usr/local/sbin/update-cloudflare-nft-set.sh || warn "Cloudflare IP set update failed"
    ok "WAN 80/443 now accept Cloudflare ranges only"
  fi
}
