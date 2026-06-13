"""MongoDB connection and helpers.

Replaces the SQLAlchemy layer entirely. Uses pymongo (sync) so workers
and FastAPI sync routes share the same thread-safe MongoClient pool.

Env vars:
  MONGODB_URL  – full connection URI  (default: mongodb://localhost:27017)
  MONGODB_DB   – database name        (default: inference_bench)
"""
import os
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.database import Database
from bson import ObjectId
from bson.errors import InvalidId

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DB_NAME     = os.getenv("MONGODB_DB", "inference_bench")

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
    return _client


def get_db() -> Database:
    """FastAPI dependency — returns the shared Database object."""
    return get_client()[DB_NAME]


def init_db() -> None:
    """Ensure indexes exist. Safe to call on every startup."""
    db = get_db()
    db.models.create_index([("provider", ASCENDING)])
    db.models.create_index([("supports_reasoning", ASCENDING)])
    db.benchmark_suites.create_index([("name", ASCENDING)], unique=True)
    db.benchmark_suites.create_index([("category", ASCENDING)])
    db.benchmark_suites.create_index([("is_recommended", ASCENDING)])
    db.evaluation_runs.create_index([("status", ASCENDING)])
    db.evaluation_runs.create_index([("created_at", DESCENDING)])
    db.run_benchmarks.create_index([("run_id", ASCENDING)])
    db.sample_outputs.create_index([("run_benchmark_id", ASCENDING)])
    db.run_notes.create_index([("run_id", ASCENDING)])
    # New collections
    db.validation_runs.create_index([("model_id", ASCENDING)])
    db.validation_runs.create_index([("created_at", DESCENDING)])
    db.endpoint_checks.create_index([("validation_run_id", ASCENDING)])
    db.benchmark_targets.create_index([("benchmark_suite_id", ASCENDING)])
    db.stress_test_runs.create_index([("model_id", ASCENDING)])
    db.stress_test_runs.create_index([("created_at", DESCENDING)])
    db.regression_alerts.create_index([("run_id", ASCENDING)])
    db.regression_alerts.create_index([("acknowledged", ASCENDING)])
    print("[db] MongoDB indexes ensured.")


# ── Document helpers ──────────────────────────────────────────────────────────

def _id(doc: dict) -> dict:
    """Replace ObjectId _id with string id field."""
    if doc is None:
        return {}
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d


def oid(id_str: str) -> ObjectId:
    """Convert string to ObjectId; raises 404-style ValueError on bad input."""
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        raise ValueError(f"Invalid id: {id_str!r}")
