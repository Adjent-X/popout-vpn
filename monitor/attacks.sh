#!/bin/bash
# Popout VPN — attack monitor (daemon mode)
# Sources live settings from /etc/popout-vpn/attacks.conf when present.
# shellcheck shell=bash

set -u

CONFIG_FILE="${POPOUT_ATTACKS_CONF:-/etc/popout-vpn/attacks.conf}"
LOG_FILE="${POPOUT_ATTACKS_LOG:-/var/log/popout-vpn/monitor.log}"

mkdir -p "$(dirname "$LOG_FILE")" /var/log/popout-vpn/captures /var/log/popout-vpn/events /etc/popout-vpn
exec >>"$LOG_FILE" 2>&1

log() {
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*"
}

load_config() {
    # Defaults
    interface="eth0"
    threshold_warning=25000
    threshold_attack=50000
    threshold_severe=100000
    threshold_critical=250000
    required_hits=5
    cooldown=300
    enable_capture=true
    capture_dir="/var/log/popout-vpn/captures"
    events_dir="/var/log/popout-vpn/events"
    capture_filter=""
    capture_packet_count=4500
    capture_snaplength=65535
    capture_promiscuous=true
    retention_days=7

    if [ -f "$CONFIG_FILE" ]; then
        # Strip CR so Windows-edited conf files still source cleanly
        local _cfg_tmp
        _cfg_tmp=$(mktemp)
        tr -d '\r' < "$CONFIG_FILE" > "$_cfg_tmp"
        # shellcheck disable=SC1090
        source "$_cfg_tmp"
        rm -f "$_cfg_tmp"
    fi

    mkdir -p "$capture_dir" "$events_dir"
    # tcpdump drops to the tcpdump user after opening the savefile; keep dir writable.
    chgrp tcpdump "$capture_dir" 2>/dev/null || true
    chmod 775 "$capture_dir" 2>/dev/null || true
}

send_discord() {
    # Discord is handled by the panel after event ingest (embed + optional pcap).
    return 0
}

send_attack_alert() {
    log "Attack alert queued for panel Discord dispatch (severity=$3 pps=$1)"
}

send_recovery_alert() {
    log "Recovery alert (pps=$1 duration=$3s) — Discord embed covers detections"
}

record_attack_event() {
    local severity="$1"
    local pps="$2"
    local bps="$3"
    local capture_path="$4"
    local kind="$5"
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local event_id
    event_id="$(date -u +%Y%m%d%H%M%S)_${attack_id}_$$"
    local event_path="${events_dir}/attack_${event_id}.json"
    local pcap_name=""
    if [ -n "$capture_path" ]; then
        pcap_name=$(basename "$capture_path")
    fi
    cat >"$event_path" <<EOF
{
  "id": "${event_id}",
  "detected_at": "${ts}",
  "severity": "${severity}",
  "pps": ${pps},
  "bps": ${bps},
  "kind": "${kind}",
  "interface": "${interface}",
  "pcap_file": "${pcap_name}",
  "packet_count": ${capture_packet_count},
  "bpf": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "${capture_filter}")
}
EOF
    log "Recorded attack event ${event_id} kind=${kind} severity=${severity} pps=${pps} bps=${bps} pcap=${pcap_name}"
}

stop_capture() {
    if [ -n "${capture_pid:-}" ] && kill -0 "$capture_pid" 2>/dev/null; then
        log "Stopping capture pid=${capture_pid}"
        kill "$capture_pid" 2>/dev/null || true
        wait "$capture_pid" 2>/dev/null || true
    fi
    capture_pid=""
}

# Start tcpdump in THIS shell (not a command-substitution subshell).
# Using capture_file=$(capture_packets) previously killed tcpdump when the
# subshell exited, leaving empty .pcap files while detection still fired.
start_capture() {
    local capture_id="$1"
    local timestamp
    timestamp=$(date -u +"%Y%m%d_%H%M%S")
    capture_file="${capture_dir}/attack_${capture_id}_${timestamp}.pcap"
    mkdir -p "$capture_dir"

    # Validate BPF up front so a bad filter cannot silently yield an empty pcap.
    if [ -n "${capture_filter}" ]; then
        # shellcheck disable=SC2086
        if ! tcpdump -i "$interface" -d $capture_filter >/dev/null 2>"${capture_dir}/.last_bpf_err"; then
            log "ERROR: BPF rejected by tcpdump; refusing capture. filter='${capture_filter}' err=$(tr '\n' ' ' <"${capture_dir}/.last_bpf_err" 2>/dev/null)"
            capture_file=""
            capture_pid=""
            return 1
        fi
    fi

    log "Starting capture: ${capture_file} packets=${capture_packet_count} filter='${capture_filter}'"

    local -a tcpdump_cmd=(tcpdump -Z root -i "$interface" -s "$capture_snaplength" -w "$capture_file" -c "$capture_packet_count")
    if [ "${capture_promiscuous}" != "true" ]; then
        tcpdump_cmd+=(-p)
    fi

    # Run in background in the service main shell so systemd keeps the job alive.
    if [ -n "${capture_filter}" ]; then
        # Intentionally unquoted so BPF tokens pass through to tcpdump
        # shellcheck disable=SC2086
        "${tcpdump_cmd[@]}" $capture_filter >>"$LOG_FILE" 2>&1 &
    else
        "${tcpdump_cmd[@]}" >>"$LOG_FILE" 2>&1 &
    fi
    capture_pid=$!

    # Brief health check: process must stay up and create the savefile.
    sleep 0.2
    if ! kill -0 "$capture_pid" 2>/dev/null; then
        wait "$capture_pid" 2>/dev/null || true
        local sz=0
        [ -f "$capture_file" ] && sz=$(stat -c%s "$capture_file" 2>/dev/null || echo 0)
        log "ERROR: tcpdump exited immediately pid_was=${capture_pid} pcap_bytes=${sz} filter='${capture_filter}'"
        capture_pid=""
        return 1
    fi
    if [ ! -f "$capture_file" ]; then
        log "ERROR: tcpdump running but pcap missing: ${capture_file}"
        return 1
    fi
    log "Capture running pid=${capture_pid} pcap=${capture_file}"
    return 0
}

cleanup_old_captures() {
    find "$capture_dir" -name "*.pcap" -type f -mtime +"$retention_days" -delete 2>/dev/null || true
    # Prune stale event JSON older than retention as well
    find "$events_dir" -name "attack_*.json" -type f -mtime +"$retention_days" -delete 2>/dev/null || true
    find "$events_dir/processed" -name "attack_*.json" -type f -mtime +"$retention_days" -delete 2>/dev/null || true
}

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

load_config
log "Starting Popout VPN attack monitor on ${interface}"
log "capture_dir=${capture_dir} retention_days=${retention_days} packet_count=${capture_packet_count}"

# Wait for dependencies (interface + tcpdump)
for _ in $(seq 1 120); do
    if command -v tcpdump >/dev/null 2>&1 && grep -qE "[[:space:]]${interface}:" /proc/net/dev; then
        break
    fi
    log "Waiting for tcpdump / ${interface}…"
    sleep 2
done

if ! command -v tcpdump >/dev/null 2>&1; then
    log "ERROR: tcpdump not found"
    exit 1
fi
if ! grep -qE "[[:space:]]${interface}:" /proc/net/dev; then
    log "ERROR: interface ${interface} not found"
    exit 1
fi

cleanup_old_captures

attack_hits=0
attack_active=0
capture_pid=""
capture_file=""
attack_id=0
attack_start_time=0
severity="WARNING"

while true; do
    load_config

    # $2 = rx bytes, $3 = rx packets (after iface name)
    read -r pkt_old bytes_old < <(awk -v iface="${interface}:" '$1 == iface {print $3, $2}' /proc/net/dev)
    if [ -z "${pkt_old:-}" ]; then
        log "ERROR: Interface ${interface} disappeared"
        sleep 5
        continue
    fi

    sleep 1
    read -r pkt_new bytes_new < <(awk -v iface="${interface}:" '$1 == iface {print $3, $2}' /proc/net/dev)
    pkt=$((pkt_new - pkt_old))
    bps=$((bytes_new - bytes_old))

    if [ "$pkt" -ge "$threshold_warning" ]; then
        attack_hits=$((attack_hits + 1))
    else
        attack_hits=0
    fi

    if [ "$attack_hits" -ge "$required_hits" ] && [ "$attack_active" -eq 0 ]; then
        if [ "$pkt" -ge "$threshold_critical" ]; then
            severity="CRITICAL"
            protection_status="CRITICAL - Manual Intervention Needed"
        elif [ "$pkt" -ge "$threshold_severe" ]; then
            severity="SEVERE"
            protection_status="ACTIVE - Protection Under Significant Load"
        elif [ "$pkt" -ge "$threshold_attack" ]; then
            severity="ATTACK"
            protection_status="ACTIVE - Mitigating Attack"
        else
            severity="WARNING"
            protection_status="ACTIVE - Monitoring Elevated Traffic"
        fi

        log "ATTACK DETECTED pps=${pkt} bps=${bps} severity=${severity}"
        attack_active=1
        attack_id=$((attack_id + 1))
        capture_file=""
        attack_start_time=$(date +%s)

        if [ "$enable_capture" = true ]; then
            start_capture "$attack_id" || true
        fi
        record_attack_event "$severity" "$pkt" "$bps" "$capture_file" "detection"
        send_attack_alert "$pkt" "$capture_file" "$severity" "$protection_status"
    fi

    if [ "$attack_active" -eq 1 ]; then
        sleep "$cooldown"

        # If tcpdump already finished (-c reached), reap it; otherwise stop after cooldown.
        if [ -n "${capture_pid:-}" ]; then
            if kill -0 "$capture_pid" 2>/dev/null; then
                stop_capture
            else
                wait "$capture_pid" 2>/dev/null || true
                capture_pid=""
            fi
            if [ -n "${capture_file:-}" ] && [ -f "$capture_file" ]; then
                log "Capture finished bytes=$(stat -c%s "$capture_file" 2>/dev/null || echo 0) file=${capture_file}"
            fi
            cleanup_old_captures
        fi

        read -r recovery_pps_old recovery_bytes_old < <(awk -v iface="${interface}:" '$1 == iface {print $3, $2}' /proc/net/dev)
        sleep 1
        read -r recovery_pps_new recovery_bytes_new < <(awk -v iface="${interface}:" '$1 == iface {print $3, $2}' /proc/net/dev)
        recovery_pkt=$((recovery_pps_new - recovery_pps_old))
        recovery_bps=$((recovery_bytes_new - recovery_bytes_old))

        if [ "$recovery_pkt" -lt "$threshold_warning" ]; then
            attack_duration=$(( $(date +%s) - attack_start_time ))
            log "ATTACK RECOVERED pps=${recovery_pkt} duration=${attack_duration}s"
            send_recovery_alert "$recovery_pkt" "$capture_file" "$attack_duration"
            attack_active=0
            attack_hits=0
            capture_file=""
            attack_start_time=0
        else
            log "Attack still active pps=${recovery_pkt} bps=${recovery_bps} — starting new capture"
            if [ "$enable_capture" = true ] && [ -z "${capture_pid:-}" ]; then
                attack_id=$((attack_id + 1))
                start_capture "$attack_id" || true
                record_attack_event "$severity" "$recovery_pkt" "$recovery_bps" "$capture_file" "recapture"
            fi
        fi
    fi
done
