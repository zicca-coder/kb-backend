from functools import lru_cache

from app.core.settings import settings


@lru_cache
def get_minio_client():
    """Build the MinIO SDK client lazily so tests can use fakes."""

    try:
        from minio import Minio
    except ImportError as exc:
        raise RuntimeError(
            "MinIO SDK is not installed. Install requirements.txt first."
        ) from exc

    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key.get_secret_value(),
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
        region=settings.minio_region or None,
    )
