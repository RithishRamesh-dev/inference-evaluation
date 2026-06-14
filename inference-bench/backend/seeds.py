"""Idempotent benchmark catalog seeder for MongoDB.

Uses update_one + upsert=True so repeated startups are safe.
"""
import json
from pymongo.database import Database

BENCHMARKS = [
    # ── Existing benchmarks ────────────────────────────────────────────────────
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

    # ── New LLM benchmarks ─────────────────────────────────────────────────────
    {
        "name": "aime24", "display_name": "AIME 2024", "category": "math",
        "description": "30 problems from the 2024 AIME competition.",
        "evalscope_id": "aime24", "default_metric": "mean_acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 30, "tags": "math,competition,reasoning,aime", "evalscope_config": "{}",
    },
    {
        "name": "amc", "display_name": "AMC", "category": "math",
        "description": "AMC 10/12 competition problems testing mathematical reasoning.",
        "evalscope_id": "amc", "default_metric": "mean_acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 40, "tags": "math,competition,amc", "evalscope_config": "{}",
    },
    {
        "name": "alpaca_eval", "display_name": "AlpacaEval 2.0", "category": "instruction",
        "description": "805 instruction-following prompts evaluated by GPT-4 as judge.",
        "evalscope_id": "alpaca_eval", "default_metric": "win_rate",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 805, "tags": "instruction,alignment,win-rate", "evalscope_config": "{}",
    },
    {
        "name": "arena_hard", "display_name": "Arena-Hard", "category": "instruction",
        "description": "500 hard real-world instructions. GPT-4o-judged win-rate vs baseline.",
        "evalscope_id": "arena_hard", "default_metric": "win_rate",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 500, "tags": "instruction,hard,arena,judge", "evalscope_config": "{}",
    },
    {
        "name": "bfcl", "display_name": "BFCL v3", "category": "tool_calling",
        "description": "Berkeley Function Calling Leaderboard v3 — 2000 diverse function call scenarios.",
        "evalscope_id": "bfcl", "default_metric": "overall_acc",
        "is_recommended": True, "is_vision": False, "requires_tools": True,
        "total_samples": 2000, "tags": "tool-calling,function,bfcl,schema", "evalscope_config": "{}",
    },
    {
        "name": "c_eval", "display_name": "C-Eval", "category": "general",
        "description": "13000-sample Chinese multi-subject evaluation benchmark.",
        "evalscope_id": "ceval-exam", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 13000, "tags": "general,chinese,knowledge,academic", "evalscope_config": "{}",
    },
    {
        "name": "cmmlu", "display_name": "CMMLU", "category": "general",
        "description": "11000-sample Chinese multi-task language understanding.",
        "evalscope_id": "cmmlu", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 11000, "tags": "general,chinese,knowledge", "evalscope_config": "{}",
    },
    {
        "name": "codeforces", "display_name": "Codeforces", "category": "coding",
        "description": "100 competitive programming problems from Codeforces.",
        "evalscope_id": "codeforces", "default_metric": "pass@1",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 100, "tags": "coding,competitive,algorithms", "evalscope_config": "{}",
    },
    {
        "name": "drop", "display_name": "DROP", "category": "reasoning",
        "description": "9536 reading comprehension questions requiring numerical reasoning.",
        "evalscope_id": "drop", "default_metric": "f1",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 9536, "tags": "reasoning,reading,numerical,comprehension", "evalscope_config": "{}",
    },
    {
        "name": "gpqa_diamond", "display_name": "GPQA Diamond", "category": "science",
        "description": "198-question diamond subset of GPQA — hardest graduate-level science questions.",
        "evalscope_id": "gpqa", "default_metric": "acc",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 198, "tags": "science,graduate,hard,diamond",
        "evalscope_config": '{"subset_list": ["gpqa_diamond"]}',
    },
    {
        "name": "humaneval_plus", "display_name": "HumanEval+", "category": "coding",
        "description": "164 Python problems with 80× more test cases than HumanEval.",
        "evalscope_id": "humaneval_plus", "default_metric": "pass@1",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 164, "tags": "coding,python,functional,rigorous", "evalscope_config": "{}",
    },
    {
        "name": "ifeval", "display_name": "IFEval", "category": "instruction",
        "description": "541 verifiable instruction-following prompts with strict format rules.",
        "evalscope_id": "ifeval", "default_metric": "prompt_acc",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 541, "tags": "instruction,format,verifiable,following", "evalscope_config": "{}",
    },
    {
        "name": "live_code_bench", "display_name": "LiveCodeBench v2", "category": "coding",
        "description": "400 live competition programming problems with contamination-free updates.",
        "evalscope_id": "live_code_bench", "default_metric": "pass@1",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 400, "tags": "coding,competitive,live,contamination-free", "evalscope_config": "{}",
    },
    {
        "name": "long_bench", "display_name": "LongBench", "category": "long_context",
        "description": "4750 samples across long-context tasks: summarization, QA, code.",
        "evalscope_id": "longbench", "default_metric": "f1",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 4750, "tags": "long-context,summarization,qa,multi-task", "evalscope_config": "{}",
    },
    {
        "name": "math500", "display_name": "MATH-500", "category": "math",
        "description": "500-problem representative sample of MATH benchmark.",
        "evalscope_id": "math500", "default_metric": "acc",
        "is_recommended": True, "is_vision": False, "requires_tools": False,
        "total_samples": 500, "tags": "math,competition,sample,hendrycks", "evalscope_config": "{}",
    },
    {
        "name": "mbpp_plus", "display_name": "MBPP+", "category": "coding",
        "description": "399 Python problems with 35× more test cases for rigorous evaluation.",
        "evalscope_id": "mbpp_plus", "default_metric": "pass@1",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 399, "tags": "coding,python,basic,rigorous", "evalscope_config": "{}",
    },
    {
        "name": "mt_bench", "display_name": "MT-Bench", "category": "instruction",
        "description": "80 multi-turn questions across 8 categories, GPT-4 judged score.",
        "evalscope_id": "mt_bench", "default_metric": "score",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 80, "tags": "instruction,multi-turn,judge,mt-bench", "evalscope_config": "{}",
    },
    {
        "name": "needle", "display_name": "Needle-in-Haystack", "category": "long_context",
        "description": "100 retrieval tasks embedded in long documents of varying lengths.",
        "evalscope_id": "needle_haystack", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 100, "tags": "long-context,retrieval,needle,memory", "evalscope_config": "{}",
    },
    {
        "name": "piqa", "display_name": "PIQA", "category": "reasoning",
        "description": "1838 physical intuition questions about everyday activities.",
        "evalscope_id": "piqa", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 1838, "tags": "reasoning,physical,commonsense", "evalscope_config": "{}",
    },
    {
        "name": "race", "display_name": "RACE", "category": "reading",
        "description": "4887 reading comprehension questions from English exams.",
        "evalscope_id": "race", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 4887, "tags": "reading,comprehension,english,exam", "evalscope_config": "{}",
    },
    {
        "name": "swe_bench_lite", "display_name": "SWE-bench Lite", "category": "coding",
        "description": "300 real GitHub issues from popular Python repos. Resolve rate metric.",
        "evalscope_id": "swe_bench_lite", "default_metric": "resolve_rate",
        "is_recommended": False, "is_vision": False, "requires_tools": True,
        "total_samples": 300, "tags": "coding,agentic,github,real-world", "evalscope_config": "{}",
    },
    {
        "name": "swe_bench_verified", "display_name": "SWE-bench Verified", "category": "coding",
        "description": "500 human-verified GitHub issues from SWE-bench.",
        "evalscope_id": "swe_bench_verified", "default_metric": "resolve_rate",
        "is_recommended": False, "is_vision": False, "requires_tools": True,
        "total_samples": 500, "tags": "coding,agentic,github,verified", "evalscope_config": "{}",
    },
    {
        "name": "tau_bench", "display_name": "τ-bench", "category": "agent",
        "description": "120 tool-interactive tasks requiring multi-step agent reasoning.",
        "evalscope_id": "tau_bench", "default_metric": "pass_rate",
        "is_recommended": False, "is_vision": False, "requires_tools": True,
        "total_samples": 120, "tags": "agent,tool,multi-step,interactive", "evalscope_config": "{}",
    },
    {
        "name": "trivia_qa", "display_name": "TriviaQA", "category": "knowledge",
        "description": "7993 trivia questions with supporting evidence documents.",
        "evalscope_id": "trivia_qa", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 7993, "tags": "knowledge,trivia,factual", "evalscope_config": "{}",
    },
    {
        "name": "truthful_qa", "display_name": "TruthfulQA", "category": "safety",
        "description": "817 questions where models mimicking human falsehoods will fail.",
        "evalscope_id": "truthful_qa", "default_metric": "mc2",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 817, "tags": "safety,truthfulness,hallucination,mc2", "evalscope_config": "{}",
    },
    {
        "name": "winogrande", "display_name": "WinoGrande", "category": "reasoning",
        "description": "1267 Winograd-schema commonsense reasoning problems.",
        "evalscope_id": "winogrande", "default_metric": "acc",
        "is_recommended": False, "is_vision": False, "requires_tools": False,
        "total_samples": 1267, "tags": "reasoning,commonsense,winograd", "evalscope_config": "{}",
    },

    # ── New VLM benchmarks ─────────────────────────────────────────────────────
    {
        "name": "chart_qa", "display_name": "ChartQA", "category": "vision",
        "description": "Chart question answering requiring visual and numerical reasoning.",
        "evalscope_id": "chartqa", "default_metric": "relaxed_acc",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 2500, "tags": "vision,chart,numerical,qa", "evalscope_config": "{}",
    },
    {
        "name": "doc_vqa", "display_name": "DocVQA", "category": "vision",
        "description": "Document Visual QA — test set with ANLS metric.",
        "evalscope_id": "doc_vqa_test", "default_metric": "anls",
        "is_recommended": True, "is_vision": True, "requires_tools": False,
        "total_samples": 5000, "tags": "vision,document,ocr,qa,anls", "evalscope_config": "{}",
    },
    {
        "name": "info_vqa", "display_name": "InfoVQA", "category": "vision",
        "description": "Infographic Visual QA requiring information extraction.",
        "evalscope_id": "info_vqa_test", "default_metric": "anls",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 2118, "tags": "vision,infographic,document,anls", "evalscope_config": "{}",
    },
    {
        "name": "math_vista", "display_name": "MathVista (Overall)", "category": "vision",
        "description": "Comprehensive MathVista with overall_acc metric across all tasks.",
        "evalscope_id": "math_vista", "default_metric": "overall_acc",
        "is_recommended": True, "is_vision": True, "requires_tools": False,
        "total_samples": 1000, "tags": "vision,math,visual,overall", "evalscope_config": "{}",
    },
    {
        "name": "mm_bench", "display_name": "MMBench", "category": "vision",
        "description": "MMBench English development set — broad multimodal capabilities.",
        "evalscope_id": "mmbench_en_dev", "default_metric": "overall_acc",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 4377, "tags": "vision,multimodal,benchmark,comprehensive", "evalscope_config": "{}",
    },
    {
        "name": "mm_vet", "display_name": "MM-Vet", "category": "vision",
        "description": "23 integrated visual capabilities tested via free-form answers.",
        "evalscope_id": "mm_vet", "default_metric": "score",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 218, "tags": "vision,free-form,integrated,capabilities", "evalscope_config": "{}",
    },
    {
        "name": "mmstar", "display_name": "MMStar", "category": "vision",
        "description": "1500 carefully filtered multimodal questions requiring true vision understanding.",
        "evalscope_id": "mmstar", "default_metric": "acc",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 1500, "tags": "vision,filtered,coarse-filtering,quality", "evalscope_config": "{}",
    },
    {
        "name": "mme", "display_name": "MME", "category": "vision",
        "description": "MME benchmark — 14 perception and cognition subtasks.",
        "evalscope_id": "mme", "default_metric": "total_score",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 2374, "tags": "vision,perception,cognition,subtasks", "evalscope_config": "{}",
    },
    {
        "name": "pope", "display_name": "POPE", "category": "vision",
        "description": "Polling-based object probing evaluation for hallucination assessment.",
        "evalscope_id": "pope", "default_metric": "f1",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 9000, "tags": "vision,hallucination,objects,probing", "evalscope_config": "{}",
    },
    {
        "name": "science_qa", "display_name": "ScienceQA", "category": "vision",
        "description": "21K multimodal science questions with explanations.",
        "evalscope_id": "scienceqa", "default_metric": "acc",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 4241, "tags": "vision,science,explanation,multimodal", "evalscope_config": "{}",
    },
    {
        "name": "seed_bench", "display_name": "SEED-Bench", "category": "vision",
        "description": "19000 multiple-choice questions across 12 evaluation dimensions.",
        "evalscope_id": "seed_bench", "default_metric": "acc",
        "is_recommended": False, "is_vision": True, "requires_tools": False,
        "total_samples": 19242, "tags": "vision,seed,comprehension,dimensions", "evalscope_config": "{}",
    },
    {
        "name": "text_vqa", "display_name": "TextVQA", "category": "vision",
        "description": "Text reading in natural images — val split with open-ended answers.",
        "evalscope_id": "textvqa_val", "default_metric": "acc",
        "is_recommended": True, "is_vision": True, "requires_tools": False,
        "total_samples": 5000, "tags": "vision,text,ocr,natural-images,reading", "evalscope_config": "{}",
    },
]

# Benchmark targets: expected/baseline scores for key benchmarks
BENCHMARK_TARGETS = [
    {"benchmark_name": "aime25",      "target_score": 0.833, "target_label": "Kimi K2.6 official"},
    {"benchmark_name": "mmlu_pro",    "target_score": 0.786, "target_label": "GPT-4o baseline"},
    {"benchmark_name": "gpqa_diamond","target_score": 0.536, "target_label": "GPT-4o baseline"},
    {"benchmark_name": "humaneval",   "target_score": 0.920, "target_label": "Claude 3.5 Sonnet"},
    {"benchmark_name": "math500",     "target_score": 0.978, "target_label": "Claude 3.7 Sonnet"},
    {"benchmark_name": "ifeval",      "target_score": 0.890, "target_label": "GPT-4o baseline"},
    {"benchmark_name": "math",        "target_score": 0.780, "target_label": "GPT-4o baseline"},
    {"benchmark_name": "gsm8k",       "target_score": 0.920, "target_label": "GPT-4o baseline"},
    {"benchmark_name": "humaneval_plus","target_score": 0.880, "target_label": "Claude 3.5 Sonnet"},
    {"benchmark_name": "mbpp_plus",   "target_score": 0.860, "target_label": "GPT-4o baseline"},
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

    # Seed benchmark targets
    for target in BENCHMARK_TARGETS:
        suite = db.benchmark_suites.find_one({"name": target["benchmark_name"]})
        if suite:
            db.benchmark_targets.update_one(
                {"benchmark_suite_id": str(suite["_id"]), "target_label": target["target_label"]},
                {"$setOnInsert": {
                    "benchmark_suite_id": str(suite["_id"]),
                    "target_score": target["target_score"],
                    "target_label": target["target_label"],
                }},
                upsert=True,
            )

    seed_judge_configs(db)


JUDGE_CONFIGS = [
    {
        "name": "response_quality",
        "description": "General response quality assessment",
        "dimensions": [
            {"name": "accuracy", "weight": 0.4, "description": "Is the answer factually correct?"},
            {"name": "completeness", "weight": 0.3, "description": "Does it fully address the question?"},
            {"name": "clarity", "weight": 0.2, "description": "Is it clearly written and well-structured?"},
            {"name": "conciseness", "weight": 0.1, "description": "Is it appropriately brief without padding?"},
        ],
        "min_score": 1, "max_score": 10,
    },
    {
        "name": "instruction_following",
        "description": "How well the model follows explicit instructions",
        "dimensions": [
            {"name": "constraint_satisfaction", "weight": 0.5, "description": "Did it follow all explicit instructions?"},
            {"name": "format_compliance", "weight": 0.3, "description": "Is the output format as requested?"},
            {"name": "tone_match", "weight": 0.2, "description": "Does the tone match the requested style?"},
        ],
        "min_score": 1, "max_score": 10,
    },
    {
        "name": "reasoning_quality",
        "description": "Quality of mathematical and logical reasoning",
        "dimensions": [
            {"name": "correctness", "weight": 0.5, "description": "Is the final answer correct?"},
            {"name": "reasoning_steps", "weight": 0.3, "description": "Are the steps logical and complete?"},
            {"name": "efficiency", "weight": 0.2, "description": "Is the reasoning appropriately concise?"},
        ],
        "min_score": 1, "max_score": 10,
    },
    {
        "name": "code_quality",
        "description": "Quality of generated code",
        "dimensions": [
            {"name": "correctness", "weight": 0.4, "description": "Does the code solve the problem?"},
            {"name": "efficiency", "weight": 0.2, "description": "Is the approach efficient?"},
            {"name": "readability", "weight": 0.2, "description": "Is the code clean and documented?"},
            {"name": "edge_cases", "weight": 0.2, "description": "Does it handle edge cases?"},
        ],
        "min_score": 1, "max_score": 10,
    },
]

def seed_judge_configs(db) -> None:
    """Seed built-in LLM judge configurations."""
    from datetime import datetime, timezone
    for cfg in JUDGE_CONFIGS:
        db.llm_judge_configs.update_one(
            {"name": cfg["name"]},
            {"$setOnInsert": {**cfg, "created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    print(f"[seeds] Judge configs: {len(JUDGE_CONFIGS)} upserted.")
