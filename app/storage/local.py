import os
from pathlib import Path

from app.core.config import settings


class LocalStorageBackend:
    def __init__(self, base_dir: str = ""):
        self.base_dir = Path(base_dir or settings.UPLOAD_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, file_key: str, data: bytes) -> str:
        path = self.base_dir / file_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    async def load(self, file_key: str) -> bytes:
        path = self.base_dir / file_key
        return path.read_bytes()

    async def delete(self, file_key: str) -> None:
        path = self.base_dir / file_key
        if path.exists():
            path.unlink()

    async def get_url(self, file_key: str, expires_in: int = 3600) -> str:
        return str(self.base_dir / file_key)


def get_storage() -> LocalStorageBackend:
    return LocalStorageBackend()
