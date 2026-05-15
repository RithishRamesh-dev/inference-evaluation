"""
benchmarks/run_ocrbench.py — OCRBench
=======================================
Official targets: think=91%  non-think=92%  (±2% tolerance)
~1000 samples from HuggingFace echo840/OCRBench.
Requires image support (IM-003/IM-004) for valid scores.
"""

import time
from pathlib import Path

from core.bench_common import bcall, score_result, save_results, print_score, normalize_ocr, TARGETS

SYSTEM = (
    "You are an OCR and document understanding expert. "
    "Extract exactly what is asked. Give only the answer, no explanation."
)


def load_dataset(limit: int = None) -> list:
    try:
        from datasets import load_dataset as hf_load
        print("  Loading OCRBench from HuggingFace...")
        ds = hf_load("echo840/OCRBench", split="test", trust_remote_code=True)
        samples = []
        for item in ds:
            samples.append({
                "id":           str(item.get("index", len(samples))),
                "question":     item.get("question", ""),
                "ground_truth": str(item.get("answers", [""])[0]
                                    if isinstance(item.get("answers"), list)
                                    else item.get("answers", "")),
                "image_url":    item.get("image_path", ""),
            })
        if limit:
            samples = samples[:limit]
        print(f"  Loaded {len(samples)} samples")
        return samples
    except ImportError:
        print("ERROR: pip install datasets")
        raise


def score_ocr(pred: str, gt: str) -> bool:
    p, g = normalize_ocr(pred), normalize_ocr(gt)
    return p == g or g in p or (p in g and len(p) > 1)


def run_sample(sample: dict, think: bool) -> dict:
    url = sample.get("image_url", "")
    if url and url.startswith("http"):
        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "text", "text": sample["question"]},
        ]}]
    else:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"[Image unavailable]\nQuestion: {sample['question']}"},
        ]
    content, _, raw = bcall(messages, think=think, max_tokens=256)
    return {
        "id": sample["id"], "ground_truth": sample["ground_truth"],
        "prediction": content[:200],
        "correct": score_ocr(content, sample["ground_truth"]),
        "has_image": bool(url and url.startswith("http")),
        "error": raw.get("error"),
    }


def run(dataset: list, mode: str, results_dir: str, delay: float) -> dict:
    think = (mode == "think")
    print(f"\n{'='*60}")
    print(f"  OCRBench — {mode.upper()}  ({len(dataset)} samples)")
    print(f"  Target: {TARGETS['ocrbench'][mode.replace('-','_')]}%  (±2%)")
    print(f"{'='*60}")

    results = []
    for i, sample in enumerate(dataset):
        r = run_sample(sample, think)
        results.append(r)
        if (i + 1) % 100 == 0:
            running = sum(x["correct"] for x in results) / len(results) * 100
            print(f"  [{i+1:04d}/{len(dataset)}] running_acc={running:.1f}%")
        if delay > 0:
            time.sleep(delay)

    n_correct = sum(r["correct"] for r in results)
    n_image   = sum(r["has_image"] for r in results)
    score     = score_result("ocrbench", mode.replace("-", "_"), n_correct, len(dataset))
    print_score(score)

    if n_image < len(dataset) * 0.5:
        print(f"\n  ⚠  Only {n_image}/{len(dataset)} samples used image input.")
        print("  Scores NOT valid until IM-003/IM-004 (image support) is fixed.")
        score["image_caveat"] = f"Only {n_image}/{len(dataset)} with image."

    save_results({"config": {"mode": mode, "n_samples": len(dataset),
                             "n_with_image": n_image},
                  "score": score, "results": results},
                 results_dir, f"ocrbench_{mode}.json")
    return score
