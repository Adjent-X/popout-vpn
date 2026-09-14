"""Resolve the published Popout VPN version from VERSION / env."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def _read_version_file() -> str | None:
    here = Path(__file__).resolve()
    candidates = (
        Path("/opt/popout-vpn/VERSION"),
        here.parents[3] / "VERSION",  # repo root when running from source
        here.parents[2].parent / "VERSION",
    )
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text.splitlines()[0].strip()
    return None


def app_version() -> str:
    file_ver = _read_version_file()
    if file_ver:
        return file_ver
    return (get_settings().APP_VERSION or "0.1.0").strip() or "0.1.0"


def github_repo_slug() -> str:
    settings = get_settings()
    slug = (getattr(settings, "GITHUB_REPO", None) or "").strip()
    if slug:
        return slug.replace("https://github.com/", "").rstrip("/")
    return ""


def github_repo_url() -> str:
    slug = github_repo_slug()
    if slug:
        return f"https://github.com/{slug}"
    return "https://github.com/Adjent-X/popout-vpn"
