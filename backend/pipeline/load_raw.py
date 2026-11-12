"""Raw layer: upload the two HI-Small files to S3 unchanged; record their SHA-256."""
from __future__ import annotations

from typing import Optional

from pipeline.common import RAW_FILES, S3_IBM_PREFIX, config_hash, ibm_dir, recorded_run, sha256_file, should_skip


def run_raw(db, force: bool = False) -> Optional[dict]:
    from pipeline import s3io
    checksums: dict[str, str] = {}
    for name in RAW_FILES:
        local = ibm_dir() / name
        if local.exists():
            checksums[name] = sha256_file(local)
        else:
            remote = s3io.head_sha256(S3_IBM_PREFIX + name)
            if remote is None:
                raise FileNotFoundError(f"{name} is neither in {ibm_dir()} nor in S3; download it first")
            checksums[name] = remote
    chash = config_hash(checksums)
    if should_skip(db, "raw", chash, force):
        return None
    with recorded_run(db, "raw", chash) as rec:
        for name in RAW_FILES:
            local = ibm_dir() / name
            if local.exists():
                s3io.upload_if_needed(local, S3_IBM_PREFIX + name)
                rec.row_counts[name] = local.stat().st_size
            else:
                rec.note(f"{name}: no local copy; S3 object already present")
        rec.extra = {"checksums": checksums}
        return checksums
