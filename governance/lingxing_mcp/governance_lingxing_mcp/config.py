import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LXConfig:
    app_id: str
    app_secret: str
    api_base: str
    host: str
    port: int
    token_cache_path: Path
    ttl_business_seconds: int
    ttl_ad_seconds: int
    ttl_inventory_seconds: int

    @classmethod
    def from_env(cls) -> "LXConfig":
        base_dir = Path(__file__).parent.parent
        return cls(
            app_id=os.environ.get("LINGXING_APP_ID", ""),
            app_secret=os.environ.get("LINGXING_APP_SECRET", ""),
            api_base=os.environ.get("LINGXING_API_BASE", "https://openapi.lingxing.com"),
            host=os.environ.get("LINGXING_HOST", "0.0.0.0"),
            port=int(os.environ.get("LINGXING_PORT", "8102")),
            token_cache_path=Path(os.environ.get("LINGXING_TOKEN_PATH", str(base_dir / "data" / "token.json"))),
            ttl_business_seconds=int(os.environ.get("LINGXING_TTL_BUSINESS", "21600")),  # 6h
            ttl_ad_seconds=int(os.environ.get("LINGXING_TTL_AD", "1800")),  # 30min
            ttl_inventory_seconds=int(os.environ.get("LINGXING_TTL_INVENTORY", "3600")),  # 1h
        )
