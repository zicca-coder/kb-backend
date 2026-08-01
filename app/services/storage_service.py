from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

import anyio

from app.core.settings import settings
from app.integrations.minio_client import get_minio_client


class ObjectResponse(Protocol):
    def read(self, amt: int | None = None) -> bytes:
        ...

    def close(self) -> None:
        ...

    def release_conn(self) -> None:
        ...


@dataclass(frozen=True, slots=True)
class StoredObject:
    data: bytes
    content_type: str
    filename: str


class StorageService:
    """Private object-storage adapter for chat attachments."""

    def __init__(
        self,
        *,
        client=None,
        bucket_name: str | None = None,
    ) -> None:
        self.client = client if client is not None else get_minio_client()
        self.bucket_name = bucket_name or settings.minio_bucket_chat_attachments

    async def ensure_bucket(self) -> None:
        def _ensure() -> None:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)

        await anyio.to_thread.run_sync(_ensure)

    async def put_object(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
    ) -> None:
        await self.ensure_bucket()

        def _put() -> None:
            self.client.put_object(
                self.bucket_name,
                object_key,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        await anyio.to_thread.run_sync(_put)

    async def get_object_bytes(self, *, object_key: str) -> bytes:
        def _get() -> bytes:
            response: ObjectResponse | None = None
            try:
                response = self.client.get_object(self.bucket_name, object_key)
                return response.read()
            finally:
                if response is not None:
                    response.close()
                    response.release_conn()

        return await anyio.to_thread.run_sync(_get)

    async def delete_object(self, *, object_key: str) -> None:
        def _delete() -> None:
            self.client.remove_object(self.bucket_name, object_key)

        await anyio.to_thread.run_sync(_delete)
