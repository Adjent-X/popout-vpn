"""Validate tcpdump/libpcap BPF filter expressions before applying."""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Prefer the live capture NIC; fall back to any/lo for compile-only checks.
_INTERFACE_CANDIDATES = ("eth0", "any", "lo")


class BpfSyntaxError(ValueError):
    """Raised when a BPF expression fails tcpdump compile."""


def validate_bpf_filter(expression: str) -> None:
    """
    Compile-check a BPF filter with tcpdump -d.
    Empty / whitespace-only is allowed (means capture all traffic).
    """
    expr = (expression or "").strip()
    if not expr:
        return
    if "\x00" in expr or len(expr) > 512:
        raise BpfSyntaxError("BPF filter is empty or too long")

    tcpdump = shutil.which("tcpdump")
    if not tcpdump:
        raise BpfSyntaxError(
            "tcpdump is not installed on the server; cannot validate BPF syntax"
        )

    last_err = "unknown error"
    for iface in _INTERFACE_CANDIDATES:
        cmd = [tcpdump, "-i", iface, "-d", expr]
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except subprocess.TimeoutExpired as exc:
            raise BpfSyntaxError("BPF validation timed out") from exc
        except OSError as exc:
            last_err = str(exc)
            continue

        if proc.returncode == 0 and (proc.stdout or "").strip():
            return

        err = (proc.stderr or proc.stdout or "").strip()
        # Wrong interface — try next candidate
        if "device" in err.lower() and (
            "no such" in err.lower() or "not found" in err.lower()
        ):
            last_err = err
            continue
        # Syntax / parse failure
        if "parse filter" in err.lower() or "syntax error" in err.lower():
            raise BpfSyntaxError(_clean_tcpdump_error(err))
        if proc.returncode != 0:
            last_err = err or f"tcpdump exited {proc.returncode}"
            # If it looks like a filter problem, stop; else try next iface
            if "filter" in last_err.lower() or "syntax" in last_err.lower():
                raise BpfSyntaxError(_clean_tcpdump_error(last_err))
            continue

    raise BpfSyntaxError(_clean_tcpdump_error(last_err))


def _clean_tcpdump_error(raw: str) -> str:
    text = " ".join((raw or "").split())
    # Typical: "tcpdump: can't parse filter expression: syntax error"
    for prefix in (
        "tcpdump: can't parse filter expression: ",
        "tcpdump: ",
    ):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix) :]
            break
    text = text.strip() or "invalid BPF filter syntax"
    if not text.lower().startswith("invalid"):
        return f"Invalid BPF filter: {text}"
    return text
