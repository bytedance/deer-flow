import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class KBConfig:
    volcengine_api_key: str
    embedding_model: str
    embedding_api_base: str
    chroma_path: Path
    host: str
    port: int
    embedding_timeout: float

    @classmethod
    def from_env(cls) -> "KBConfig":
        base_dir = Path(__file__).parent.parent
        return cls(
            volcengine_api_key=os.environ.get("VOLCENGINE_API_KEY", ""),
            embedding_model=os.environ.get(
                "KB_EMBEDDING_MODEL", "doubao-embedding-text-240715"
            ),
            embedding_api_base=os.environ.get(
                "KB_EMBEDDING_API_BASE",
                "https://ark.cn-beijing.volces.com/api/v3",
            ),
            chroma_path=Path(
                os.environ.get("KB_CHROMA_PATH", str(base_dir / "data" / "chroma_db"))
            ),
            host=os.environ.get("KB_HOST", "0.0.0.0"),
            port=int(os.environ.get("KB_PORT", "8101")),
            embedding_timeout=float(
                os.environ.get("KB_EMBEDDING_TIMEOUT", "10.0")
            ),
        )
