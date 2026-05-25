from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SotaTrackerPaths:
    research_root: Path
    models_root: Path
    cache_root: Path

    @classmethod
    def default(cls) -> "SotaTrackerPaths":
        return cls(
            research_root=Path(os.environ.get("RESEARCH_DIR", "/home/data_1/research")),
            models_root=Path(os.environ.get("MODELS_DIR", "/home/data_0/models")),
            cache_root=Path(os.environ.get("CACHE_DIR", "/home/data_0/cache")),
        )

    @property
    def tapnet_repo(self) -> Path:
        return self.research_root / "tapnet"

    @property
    def cotracker_repo(self) -> Path:
        return self.research_root / "co-tracker"

    @property
    def tapnextpp_checkpoint(self) -> Path:
        return self.models_root / "tapnet" / "tapnextpp_checkpoint.pt"

    @property
    def cotracker_offline_checkpoint(self) -> Path:
        return self.models_root / "cotracker3" / "scaled_offline.pth"

    @property
    def cotracker_online_checkpoint(self) -> Path:
        return self.models_root / "cotracker3" / "scaled_online.pth"

    @property
    def venv(self) -> Path:
        return self.cache_root / "tmp" / "golf15-sota-trackers-venv"

    def ensure_dirs(self) -> None:
        for path in (self.research_root, self.models_root / "tapnet", self.models_root / "cotracker3", self.cache_root / "pip", self.cache_root / "huggingface", self.cache_root / "tmp"):
            path.mkdir(parents=True, exist_ok=True)


def proxy_environment(base: dict[str, str] | None = None, *, proxy: str = "http://127.0.0.1:7897", paths: SotaTrackerPaths | None = None) -> dict[str, str]:
    paths = paths or SotaTrackerPaths.default()
    env = dict(base or os.environ)
    env.update({
        "http_proxy": proxy,
        "https_proxy": proxy,
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "PIP_CACHE_DIR": str(paths.cache_root / "pip"),
        "HF_HOME": str(paths.cache_root / "huggingface"),
        "TORCH_HOME": str(paths.models_root / "torch"),
    })
    return env
