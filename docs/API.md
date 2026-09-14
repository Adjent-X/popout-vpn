# Machine API (`/api/v1`)

Popout VPN ships a versioned REST API for billing systems, bots, and ops scripts. Session JWTs from the browser **do not** work here — create a key under **Account → API keys**.

Keys look like `pk_live_<prefix>_<secret>` and are shown **once**. Send either:

```http
Authorization: Bearer pk_live_…
X-Api-Key: pk_live_…
```

If Cloudflare WAF sync is on, valid keys are allowlisted at the edge for `/api/v1`. Invalid or missing keys never reach the origin for that path.

## Scopes

| Scope | Access |
|---|---|
| `configs:create` | `POST /api/v1/configs` |
| `configs:revoke` | `DELETE /api/v1/configs/{id}` |
| `configs:logs` | `GET /api/v1/configs/{id}/connection-logs` |
| `analytics:read` | `GET /api/v1/analytics/overview` |
| `settings:write` | `GET`/`PATCH /api/v1/site-settings` (full-admin keys only) |

Missing scope → `403`. Keys inherit the owner’s **role** and **ownership**: a sub-admin key can only touch that sub-admin’s configs and stats.

## Endpoints

**Health** — any valid key:

```bash
curl -sS "$BASE/api/v1/health" -H "Authorization: Bearer $API_KEY"
```

**Create a client** — provide `expiry_days` (`7|30|90|365`) or `expires_at`:

```bash
curl -sS -X POST "$BASE/api/v1/configs" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"label":"laptop-alice","expiry_days":30}'
```

Response includes metadata and the full `.ovpn` body (`201`).

**Revoke** — active/expired configs soft-revoke (`200`); already-revoked configs hard-delete (`204`):

```bash
curl -sS -X DELETE "$BASE/api/v1/configs/$CONFIG_ID" \
  -H "Authorization: Bearer $API_KEY"
```

**Connection logs** — newest first, max 200 events.

**Analytics overview** — host metrics, client counts, bandwidth, attack totals. Query: `hours=1–168`, `include_series=true|false`. Extra throttle: at least 2.5s between calls per key (configurable).

**Site settings** — full-admin keys with `settings:write` can read (secrets redacted) and patch shaping, WAN IP policy, and `duplicate_cn_mode`.

The in-app **API docs** tab is generated from the same contract and uses your live origin as `$BASE`.

## Rate limits

- Per-key sliding window (default 60/min, set at key creation) → `429` + `Retry-After`
- Analytics overview also enforces a minimum interval (default 2.5s)
- Login/register stay on the browser API and have their own IP + email caps
