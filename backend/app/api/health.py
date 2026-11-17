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


@router.get("/meta")
def meta() -> dict:
    """What the UI needs to build valid scenarios: slice length and the payment formats in the data."""
    from app.api.common import jsonable
    d = db.get_db()
    m = d.pipeline_meta.find_one({"_id": "meta"}, {"_id": 0}) or {}
    return jsonable({"data_loaded": bool(m), "slice_hours": m.get("slice_hours"), "data_origin": m.get("data_origin"),
                     "slice_end": m.get("slice_end"), "dataset": m.get("dataset"),
                     "payment_formats": sorted(d.stg_transactions.distinct("payment_format")) if m else [],
                     "model_id": get_settings().llm_model_id, "prompt_version": get_settings().prompt_version})
