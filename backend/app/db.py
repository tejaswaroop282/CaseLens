"""MongoDB access (sync pymongo, decision D4)."""
from __future__ import annotations

from functools import lru_cache

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

from app.config import get_settings


@lru_cache
def get_client() -> MongoClient:
    return MongoClient(get_settings().mongo_uri, serverSelectionTimeoutMS=3000, tz_aware=True)


def get_db() -> Database:
    return get_client().get_default_database()


def ping() -> bool:
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False


def ensure_indexes(db: Database | None = None) -> None:
    """Indexes from docs/01 section 7. Collections are created lazily by Mongo."""
    db = db if db is not None else get_db()
    db.stg_transactions.create_index("tx_id", unique=True)
    db.stg_transactions.create_index([("from_account", ASCENDING), ("ts", ASCENDING)])
    db.stg_transactions.create_index([("to_account", ASCENDING), ("ts", ASCENDING)])
    db.stg_labels.create_index("tx_id", unique=True)
    db.stg_pattern_blocks.create_index("pattern_id", unique=True)
    db.stg_pattern_blocks.create_index("pattern_type")
    db.alert_truth.create_index("alert_id", unique=True)
    db.alerts.create_index("alert_id", unique=True)
    db.alerts.create_index([("scenario_id", ASCENDING), ("status", ASCENDING)])
    db.alerts.create_index("account_id")
    db.cases.create_index("case_id", unique=True)
    db.cases.create_index("alert_id")
    db.decisions.create_index("case_id")
    db.scenarios.create_index("scenario_id", unique=True)
    db.llm_usage.create_index("ts")
