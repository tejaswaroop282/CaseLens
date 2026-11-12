"""S3 raw layer: upload unchanged files with their SHA-256, download when the local cache is missing."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.config import get_settings
from pipeline.common import log, sha256_file


@lru_cache
def client():
    import boto3
    s = get_settings()
    if not s.s3_bucket:
        raise RuntimeError("S3_BUCKET is not set in .env")
    return boto3.Session(profile_name=s.aws_profile, region_name=s.aws_region).client("s3")


def bucket() -> str:
    return get_settings().s3_bucket


def head_sha256(key: str) -> Optional[str]:
    """SHA-256 stored in the object's metadata, or None if the object does not exist."""
    from botocore.exceptions import ClientError
    try:
        return client().head_object(Bucket=bucket(), Key=key)["Metadata"].get("sha256")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def upload_if_needed(path: Path, key: str) -> str:
    """Upload unless an object with the same checksum exists. Raw objects are never modified."""
    digest = sha256_file(path)
    remote = head_sha256(key)
    if remote == digest:
        log.info("s3_exists", key=key)
        return digest
    if remote is not None:
        raise RuntimeError(f"s3://{bucket()}/{key} exists with a different checksum; raw objects are never "
                           "overwritten. Delete it by hand if the source really changed.")
    client().upload_file(str(path), bucket(), key, ExtraArgs={"Metadata": {"sha256": digest}})
    log.info("s3_uploaded", key=key, bytes=path.stat().st_size)
    return digest


def ensure_local(path: Path, key: str) -> Path:
    """Download from S3 when the local cache file is missing; verify the checksum."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    client().download_file(bucket(), key, str(tmp))
    expected = head_sha256(key)
    if expected and sha256_file(tmp) != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch downloading {key}")
    tmp.replace(path)
    log.info("s3_downloaded", key=key)
    return path
