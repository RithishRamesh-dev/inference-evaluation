"""Idempotent benchmark catalog seeder for MongoDB.

Uses update_one + upsert=True so repeated startups are safe.
"""
import json
from pymongo.database import Database

BENCHMARKS = [
    {
        "name": "aime25", "display_name": "AIME 2025", "category": "math",
        "description": "30 problems from the 2025 AIME. Best with thinking mode.",
        "evalscope_id": "aime25", "default_metric": "mean_acc",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 30, "tags": "math,competition,reasoning", "evalscope_config": "{}",
    },
    {
        "name": "mmlu_pro", "display_name": "MMLU-Pro", "category": "general",
        "description": "1730-sample professional multi-task language understanding.",
        "evalscope_id": "mmlu_pro", "default_metric": "mean_acc",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 1730, "tags": "general,knowledge,academic", "evalscope_config": "{}",
    },
    {
        "name": "ocr_bench", "display_name": "OCRBench", "category": "vision",
        "description": "1000-sample OCR eval across 10 sub-categories. Requires vision.",
        "evalscope_id": "ocr_bench", "default_metric": "acc",
        "is_recommended": True, "is_vision": True, "requires_tools": False,
        "total_samples": 1000, "tags": "vision,ocr,multimodal", "evalscope_config": "{}",
    },
    {
        "name": "gpqa", "display_name": "GPQA", "category": "science",
        "description": "Graduate-level scientific Q&A — biology, chemistry, physics.",
        "evalscope_id": "gpqa", "default_metric": "acc",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 448, "tags": "science,graduate,reasoning", "evalscope_config": "{}",
    },
    {
        "name": "gsm8k", "display_name": "GSM8K", "category": "math",
        "description": "8500 grade-school math word problems.",
        "evalscope_id": "gsm8k", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 8500, "tags": "math,arithmetic", "evalscope_config": "{}",
    },
    {
        "name": "humaneval", "display_name": "HumanEval", "category": "coding",
        "description": "164 hand-crafted Python programming problems.",
        "evalscope_id": "humaneval", "default_metric": "pass@1",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 164, "tags": "coding,python,functional", "evalscope_config": "{}",
    },
    {
        "name": "mbpp", "display_name": "MBPP", "category": "coding",
        "description": "Mostly Basic Python Problems — 374 crowd-sourced tasks.",
        "evalscope_id": "mbpp", "default_metric": "pass@1",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 374, "tags": "coding,python,basic", "evalscope_config": "{}",
    },
    {
        "name": "k2_verifier", "display_name": "K2 Vendor Verifier", "category": "tool_calling",
        "description": "K2VV: tool-call trigger similarity and schema accuracy.",
        "evalscope_id": "k2_verifier", "default_metric": "trigger_similarity",
        "is_recommended": True, "is_vision": False, "requires_tools": True,
        "total_samples": 200, "tags": "tool-calling,schema,vendor", "evalscope_config": "{}",
    },
    {
        "name": "kimi_verifier", "display_name": "Kimi Verifier", "category": "compliance",
        "description": "API parameter enforcement — param_reject_rate.",
        "evalscope_id": "kimi_verifier", "default_metric": "param_reject_rate",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 100, "tags": "compliance,api,kimi", "evalscope_config": "{}",
    },
    {
        "name": "bbh", "display_name": "BIG-Bench Hard", "category": "reasoning",
        "description": "23 challenging BIG-Bench tasks requiring multi-step reasoning.",
        "evalscope_id": "bbh", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 6511, "tags": "reasoning,multi-step", "evalscope_config": "{}",
    },
    {
        "name": "arc", "display_name": "ARC Challenge", "category": "reasoning",
        "description": "AI2 Reasoning Challenge — grade-school science questions.",
        "evalscope_id": "arc", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 1172, "tags": "reasoning,science", "evalscope_config": "{}",
    },
    {
        "name": "math", "display_name": "MATH", "category": "math",
        "description": "Competition mathematics — algebra, geometry, number theory.",
        "evalscope_id": "math", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 5000, "tags": "math,competition", "evalscope_config": "{}",
    },
    {
        "name": "livecodebench", "display_name": "LiveCodeBench", "category": "coding",
        "description": "Live competition programming problems.",
        "evalscope_id": "livecodebench", "default_metric": "pass@1",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 400, "tags": "coding,competitive,live", "evalscope_config": "{}",
    },
    {
        "name": "mmmu", "display_name": "MMMU", "category": "vision",
        "description": "Multi-modal university Q&A across 30 disciplines. Requires vision.",
        "evalscope_id": "mmmu", "default_metric": "acc",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 11550, "tags": "vision,multimodal,university", "evalscope_config": "{}",
    },
    {
        "name": "mathvista", "display_name": "MathVista", "category": "vision",
        "description": "Math reasoning in visual contexts — charts and diagrams. Requires vision.",
        "evalscope_id": "mathvista", "default_metric": "acc",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 1000, "tags": "vision,math,visual", "evalscope_config": "{}",
    },
]


def seed_benchmarks(db: Database) -> None:
    added = 0
    for data in BENCHMARKS:
        result = db.benchmark_suites.update_one(
            {"name": data["name"]},
            {"$setOnInsert": data},
            upsert=True,
        )
        if result.upserted_id:
            added += 1
    if added:
        print(f"[seeds] Inserted {added} benchmark(s).")
    else:
        print("[seeds] Benchmark catalog up to date.")
