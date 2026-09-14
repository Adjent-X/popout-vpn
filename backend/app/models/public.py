from pydantic import BaseModel, Field


class BrandColors(BaseModel):
    background: str
    primary: str
    accent: str
    accent_bright: str


class BrandConfig(BaseModel):
    name: str
    product: str
    site_title: str = "Popout VPN Admin"
    colors: BrandColors


class PublicConfigResponse(BaseModel):
    turnstile_enabled: bool
    turnstile_site_key: str = Field(
        description="Empty when Turnstile is disabled",
    )
    brand: BrandConfig
    warp_routing_enabled: bool = True
    duplicate_cn_mode: bool = False
    public_gate_enabled: bool = False
    public_gate_unlocked: bool = True


class PublicGateUnlockRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class PublicGateUnlockResponse(BaseModel):
    unlocked: bool = True
