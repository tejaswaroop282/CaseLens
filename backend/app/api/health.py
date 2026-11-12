from __future__ import annotations

from fastapi import APIRouter

from app import db
from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    s = get_settings()
    mongo_ok = db.ping()
    data_loaded = False
    tokens_remaining = None
    if mongo_ok:
        data_loaded = db.get_db().pipeline_meta.find_one({"_id": "meta"}) is not None
        from app.llm import get_chat_ledger
        tokens_remaining = get_chat_ledger().remaining()
    return {
        "status": "ok" if mongo_ok else "degraded",
        "mongo": mongo_ok,
        "chroma": s.chroma_path.exists(),
        "data_loaded": data_loaded,
        "tokens_remaining": tokens_remaining,
    }
