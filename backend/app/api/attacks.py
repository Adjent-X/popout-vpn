"""Full-admin attack capture APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import require_full_admin
from app.services.attacks import (
    attack_stats,
    delete_pcap_and_events,
    ingest_attack_events,
    list_attack_events,
    list_pcap_files,
    resolve_pcap,
)

router = APIRouter(prefix="/api/attacks", tags=["attacks"])


class AttackPcapItem(BaseModel):
    name: str
    size_bytes: int
    modified_at: datetime


class AttackEventItem(BaseModel):
    id: str
    detected_at: datetime | None = None
    severity: str
    kind: str = "detection"
    pps: int = 0
    bps: int = 0
    interface: str = "eth0"
    pcap_file: str | None = None
    pcap_available: bool = False
    pcap_size_bytes: int | None = None
    pcap_modified_at: datetime | None = None
    bpf: str = ""
    discord_sent: bool = False


class AttackPcapListResponse(BaseModel):
    captures: list[AttackPcapItem] = Field(default_factory=list)
    events: list[AttackEventItem] = Field(default_factory=list)
    attacks_lifetime: int = 0
    attacks_24h: int = 0


@router.get("", response_model=AttackPcapListResponse)
async def list_attacks(
    _admin: dict = Depends(require_full_admin),
) -> AttackPcapListResponse:
    await ingest_attack_events()
    # Counts + event rows without a second filesystem ingest.
    stats = await attack_stats(ingest=False, max_cache_age=0)
    captures = [
        AttackPcapItem(
            name=row["name"],
            size_bytes=row["size_bytes"],
            modified_at=row["modified_at"],
        )
        for row in list_pcap_files()
    ]
    events_raw = await list_attack_events(ingest=False)
    events = [AttackEventItem(**row) for row in events_raw]
    return AttackPcapListResponse(
        captures=captures,
        events=events,
        attacks_lifetime=stats["attacks_lifetime"],
        attacks_24h=stats["attacks_24h"],
    )


@router.get("/{name}/analysis")
async def analyze_attack_pcap(
    name: str,
    force: bool = Query(False),
    _admin: dict = Depends(require_full_admin),
) -> dict[str, Any]:
    try:
        from app.services.pcap_analysis import analyze_pcap

        return analyze_pcap(name, force=force)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Capture not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {exc}",
        ) from exc


@router.get("/{name}/download")
async def download_attack_pcap(
    name: str,
    _admin: dict = Depends(require_full_admin),
) -> FileResponse:
    try:
        path = resolve_pcap(name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Capture not found") from exc
    return FileResponse(
        path,
        media_type="application/vnd.tcpdump.pcap",
        filename=name,
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attack_pcap(
    name: str,
    _admin: dict = Depends(require_full_admin),
) -> None:
    try:
        await delete_pcap_and_events(name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Capture not found") from exc
