from datetime import datetime

from pydantic import BaseModel, Field


class MetricPoint(BaseModel):
    ts: datetime
    cpu_percent: float | None = None
    mem_percent: float | None = None
    disk_percent: float | None = None
    net_bytes_sent_rate: float | None = None
    net_bytes_recv_rate: float | None = None
    net_packets_sent_rate: float | None = None
    net_packets_recv_rate: float | None = None
    eth0_bytes_sent_rate: float | None = None
    eth0_bytes_recv_rate: float | None = None
    eth0_packets_sent_rate: float | None = None
    eth0_packets_recv_rate: float | None = None
    tun0_bytes_sent_rate: float | None = None
    tun0_bytes_recv_rate: float | None = None
    tun0_packets_sent_rate: float | None = None
    tun0_packets_recv_rate: float | None = None


class HostMetricsLatest(BaseModel):
    ts: datetime
    cpu_percent: float
    mem_total: int
    mem_used: int
    mem_percent: float
    disk_total: int
    disk_used: int
    disk_percent: float
    net_bytes_sent: int
    net_bytes_recv: int
    net_bytes_sent_rate: float
    net_bytes_recv_rate: float
    net_packets_sent: int = 0
    net_packets_recv: int = 0
    net_packets_sent_rate: float = 0.0
    net_packets_recv_rate: float = 0.0
    eth0_bytes_sent: int = 0
    eth0_bytes_recv: int = 0
    eth0_packets_sent: int = 0
    eth0_packets_recv: int = 0
    eth0_bytes_sent_rate: float = 0.0
    eth0_bytes_recv_rate: float = 0.0
    eth0_packets_sent_rate: float = 0.0
    eth0_packets_recv_rate: float = 0.0
    tun0_bytes_sent: int = 0
    tun0_bytes_recv: int = 0
    tun0_packets_sent: int = 0
    tun0_packets_recv: int = 0
    tun0_bytes_sent_rate: float = 0.0
    tun0_bytes_recv_rate: float = 0.0
    tun0_packets_sent_rate: float = 0.0
    tun0_packets_recv_rate: float = 0.0
    load_avg: list[float] | None = None


class BandwidthToDate(BaseModel):
    eth0_bytes_sent: int = 0
    eth0_bytes_recv: int = 0
    tun0_bytes_sent: int = 0
    tun0_bytes_recv: int = 0
    total_bytes: int = 0
    sample_seconds: float = 0
    avg_bps: float = 0
    started_at: datetime | None = None
    updated_at: datetime | None = None


class MonthlyBandwidth(BaseModel):
    id: str
    year: int
    month: int
    eth0_bytes_sent: int = 0
    eth0_bytes_recv: int = 0
    tun0_bytes_sent: int = 0
    tun0_bytes_recv: int = 0
    total_bytes: int = 0
    sample_seconds: float = 0
    avg_bps: float = 0


class AnalyticsOverview(BaseModel):
    latest: HostMetricsLatest | None = None
    series: list[MetricPoint] = Field(default_factory=list)
    clients_online: int = 0
    clients_total_active: int = 0
    configs_total: int = 0
    configs_revoked: int = 0
    attacks_lifetime: int = 0
    attacks_24h: int = 0
    bandwidth_to_date: BandwidthToDate | None = None
    bandwidth_monthly: list[MonthlyBandwidth] = Field(default_factory=list)


class ConnectionLogEntry(BaseModel):
    id: str
    at: datetime
    event: str
    client_name: str
    wan_ip: str | None = None
    vpn_ip: str | None = None
    wan_logged: bool = False
