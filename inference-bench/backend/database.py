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

    # Playground
    db.playground_templates.create_index([("created_at", DESCENDING)])

    # LLM Judge
    db.llm_judge_configs.create_index([("name", ASCENDING)], unique=True)
    db.llm_judge_results.create_index([("run_benchmark_id", ASCENDING)])

    # Model pricing
    db.model_pricing.create_index([("model_id", ASCENDING)])

    # Budget configs
    db.budget_configs.create_index([("model_id", ASCENDING)])

    # Scheduled evaluations
    db.scheduled_evaluations.create_index([("model_id", ASCENDING)])
    db.scheduled_evaluations.create_index([("enabled", ASCENDING)])
    db.scheduled_evaluations.create_index([("next_run_at", ASCENDING)])

    # Webhook keys
    db.webhook_keys.create_index([("created_at", DESCENDING)])

    # Custom datasets
    db.custom_datasets.create_index([("created_at", DESCENDING)])
    db.custom_dataset_items.create_index([("dataset_id", ASCENDING)])

    # Probe history
    db.probe_history.create_index([("created_at", DESCENDING)])
    db.probe_history.create_index([("endpoint_url", ASCENDING)])

    # Monitor
    db.monitor_configs.create_index([("model_id", ASCENDING)])
    db.monitor_configs.create_index([("enabled", ASCENDING)])
    db.monitor_results.create_index([("monitor_config_id", ASCENDING)])
    db.monitor_results.create_index([("run_at", DESCENDING)])

    # Load profiling
    db.load_samples.create_index([("model_id", ASCENDING)])
    db.load_samples.create_index([("sampled_at", DESCENDING)])
    db.load_samples.create_index([("model_id", ASCENDING), ("sampled_at", DESCENDING)])

    # A/B tests
    db.ab_test_runs.create_index([("created_at", DESCENDING)])
    db.ab_test_runs.create_index([("status", ASCENDING)])

    # Eval templates
    db.eval_templates.create_index([("created_at", DESCENDING)])

    # Benchmark relationships
    db.benchmark_relationships.create_index([("source_benchmark_id", ASCENDING)])
    db.benchmark_relationships.create_index([("target_benchmark_id", ASCENDING)])

    # Benchmarking Evaluation — GPU droplets
    db.gpu_droplets.create_index([("status", ASCENDING)])
    db.gpu_droplets.create_index([("created_at", DESCENDING)])

    # Benchmarking Evaluation — deployments
    db.deployments.create_index([("droplet_id", ASCENDING)])
    db.deployments.create_index([("status", ASCENDING)])
    db.deployments.create_index([("created_at", DESCENDING)])

    # Benchmarking Evaluation — on-droplet agent
    db.gpu_droplets.create_index([("agent_token_sha256", ASCENDING)])
    db.agent_jobs.create_index([("droplet_id", ASCENDING), ("status", ASCENDING), ("created_at", ASCENDING)])
    db.agent_jobs.create_index([("deployment_id", ASCENDING)])

    # Better composite indexes
    db.evaluation_runs.create_index([("model_id", ASCENDING), ("created_at", DESCENDING)])
    db.evaluation_runs.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    db.run_benchmarks.create_index([("run_id", ASCENDING), ("status", ASCENDING)])
    db.sample_outputs.create_index([("run_benchmark_id", ASCENDING), ("is_correct", ASCENDING)])

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
