"""
benchmarks/run_mmmu.py — MMMU Pro
===================================
Official targets: think=78.8% (Vision)  non-think=74.9%  (±2% tolerance)
HuggingFace MMMU/MMMU_Pro. Multi-choice A/B/C/D/E.
Requires image support for Vision subset.
"""

import time
from pathlib import Path

from core.bench_common import bcall, score_result, save_results, print_score, extract_choice, TARGETS

SYSTEM = (
    "You are an expert academic reasoner across all disciplines. "
    "Think through the problem carefully, then write your final answer "
    "on the last line as: Answer: <letter>"
)


def load_dataset(limit: int = None, split: str = "test") -> list:
    try:
        from datasets import load_dataset as hf_load
        print("  Loading MMMU Pro from HuggingFace...")
        ds = hf_load("MMMU/MMMU_Pro", split=split, trust_remote_code=True)
        samples = []
        for item in ds:
            image_urls = []
            for key in ["image_1", "image_2", "image_3"]:
                img = item.get(key)
                if img and hasattr(img, "url"):
                    image_urls.append(img.url)
                elif img and isinstance(img, str) and img.startswith("http"):
                    image_urls.append(img)

            choices = []
            for letter in ["A", "B", "C", "D", "E"]:
                val = item.get(f"option_{letter.lower()}", item.get(letter))
                if val:
                    choices.append(f"{letter}: {val}")

            samples.append({
                "id":         str(item.get("id", len(samples))),
                "question":   item.get("question", ""),
                "choices":    choices,
                "answer":     str(item.get("answer", "")).upper(),
                "domain":     item.get("subject", item.get("category", "unknown")),
                "image_urls": image_urls,
            })
        if limit:
            samples = samples[:limit]
        print(f"  Loaded {len(samples)} samples")
        return samples
    except ImportError:
        print("ERROR: pip install datasets")
        raise


def run_sample(sample: dict, think: bool) -> dict:
    question_text = (
        f"Question: {sample['question']}\n\n"
        f"Choices:\n" + "\n".join(sample["choices"]) +
        "\n\nAnswer: <letter>"
    )
    urls = [u for u in sample.get("image_urls", []) if u and u.startswith("http")]
    if urls:
        content = [{"type": "image_url", "image_url": {"url": u}} for u in urls]
        content.append({"type": "text", "text": question_text})
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user",   "content": question_text}]

    content_str, _, raw = bcall(messages, think=think, max_tokens=1024)
    extracted = extract_choice(content_str)
    correct   = (extracted == sample["answer"]) if extracted else False
    return {
        "id": sample["id"], "domain": sample["domain"],
        "answer": sample["answer"], "extracted": extracted, "correct": correct,
        "has_image": bool(urls), "error": raw.get("error"),
    }


def run(dataset: list, mode: str, results_dir: str, delay: float) -> dict:
    think    = (mode == "think")
    mode_key = mode.replace("-", "_")
    print(f"\n{'='*60}")
    print(f"  MMMU Pro — {mode.upper()}  ({len(dataset)} samples)")
    print(f"  Target: {TARGETS['mmmu_pro'][mode_key]}%  (±2%)")
    print(f"{'='*60}")

    results       = []
    domain_scores: dict[str, list] = {}
    for i, sample in enumerate(dataset):
        r = run_sample(sample, think)
        results.append(r)
        domain_scores.setdefault(r["domain"], []).append(r["correct"])
        if (i + 1) % 100 == 0:
            running = sum(x["correct"] for x in results) / len(results) * 100
            print(f"  [{i+1:04d}/{len(dataset)}] running_acc={running:.1f}%")
        if delay > 0:
            time.sleep(delay)

    n_correct = sum(r["correct"] for r in results)
    n_image   = sum(r["has_image"] for r in results)
    score     = score_result("mmmu_pro", mode_key, n_correct, len(dataset))
    print_score(score)

    print("\n  Domain breakdown:")
    for domain, correct_list in sorted(domain_scores.items()):
        acc = sum(correct_list) / len(correct_list) * 100
        print(f"    {domain:<30} {acc:.1f}%  ({sum(correct_list)}/{len(correct_list)})")

    if n_image < len(dataset) * 0.5:
        print(f"\n  ⚠  Only {n_image}/{len(dataset)} samples used image input.")
        score["image_caveat"] = f"Only {n_image}/{len(dataset)} with image."

    save_results({"config": {"mode": mode, "n_samples": len(dataset)},
                  "score": score,
                  "domain_scores": {d: {"correct": sum(v), "total": len(v),
                                        "accuracy": round(sum(v)/len(v)*100, 1)}
                                    for d, v in domain_scores.items()},
                  "results": results},
                 results_dir, f"mmmu_pro_{mode}.json")
    return score
