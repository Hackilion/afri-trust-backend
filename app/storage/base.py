from typing import Protocol


class StorageBackend(Protocol):
    async def save(self, file_key: str, data: bytes) -> str:
        """Save data and return the storage path / key."""
        ...

    async def load(self, file_key: str) -> bytes:
        """Load data by key."""
        ...

    async def delete(self, file_key: str) -> None: ...

    async def get_url(self, file_key: str, expires_in: int = 3600) -> str:
        """Return a URL (or path) for the stored file."""
        ...
