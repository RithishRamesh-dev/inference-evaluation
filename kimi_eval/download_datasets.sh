#!/bin/bash
# Run this ONCE on the droplet to download benchmark datasets.
# Requires internet access (run outside Docker, on the host).
set -e

echo "=== K2.6 Dataset Downloader ==="
echo "This downloads OCRBench and MMMU Pro to ./datasets/"
echo "Run once on the droplet — internet required."
echo ""

mkdir -p datasets/ocrbench datasets/mmmu_pro

# Install required Python packages
pip install datasets huggingface_hub pillow -q

python3 << 'PYEOF'
import json, base64, io, os
from pathlib import Path

# ── OCRBench ──────────────────────────────────────────────────────────────────
print("Downloading OCRBench (~1000 samples)...")
try:
    from datasets import load_dataset
    ds = load_dataset("cat-claws/all-ocr-vqa", split="test")
    
    out = []
    for i, item in enumerate(ds):
        img = item.get("image")
        if img is None:
            continue
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        out.append({
            "id":       i,
            "question": item.get("question", item.get("Question", "")),
            "answer":   str(item.get("answer", item.get("Answer", ""))),
            "image_b64": b64,
        })
        if (i+1) % 100 == 0:
            print(f"  {i+1}/{len(ds)} processed")
    
    with open("datasets/ocrbench/ocrbench.jsonl", "w") as f:
        for item in out:
            f.write(json.dumps(item) + "\n")
    print(f"OCRBench: saved {len(out)} samples -> datasets/ocrbench/ocrbench.jsonl")
except Exception as e:
    print(f"OCRBench download failed: {e}")
    print("Trying alternative dataset...")
    try:
        ds2 = load_dataset("echo840/OCRBench", split="test")
        out = []
        for i, item in enumerate(ds2):
            img = item.get("image")
            if img is None: continue
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            out.append({
                "id": i,
                "question": item.get("question",""),
                "answer": str(item.get("answer","")),
                "image_b64": b64,
            })
        with open("datasets/ocrbench/ocrbench.jsonl", "w") as f:
            for item in out: f.write(json.dumps(item) + "\n")
        print(f"OCRBench (alt): saved {len(out)} samples")
    except Exception as e2:
        print(f"Alt also failed: {e2}")

# ── MMMU Pro ──────────────────────────────────────────────────────────────────
print("\nDownloading MMMU Pro (~500 samples)...")
try:
    from datasets import load_dataset
    ds = load_dataset("MMMU/MMMU_Pro", "standard", split="test")
    
    out = []
    for i, item in enumerate(ds):
        images_b64 = []
        for j in range(1, 8):
            img = item.get(f"image_{j}")
            if img is not None:
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                images_b64.append(base64.b64encode(buf.getvalue()).decode())
        
        question = item.get("question", "")
        options  = item.get("options", [])
        if options:
            opts_str = "\n".join(f"{chr(65+k)}. {v}" for k, v in enumerate(options))
            question = f"{question}\n\n{opts_str}"
        
        out.append({
            "id":         i,
            "question":   question,
            "answer":     str(item.get("answer", "")),
            "images_b64": images_b64,
            "subject":    item.get("subject", ""),
        })
        if (i+1) % 50 == 0:
            print(f"  {i+1} processed")
    
    with open("datasets/mmmu_pro/mmmu_pro.jsonl", "w") as f:
        for item in out:
            f.write(json.dumps(item) + "\n")
    print(f"MMMU Pro: saved {len(out)} samples -> datasets/mmmu_pro/mmmu_pro.jsonl")
except Exception as e:
    print(f"MMMU Pro download failed: {e}")

print("\nDone. Now rebuild Docker and run:")
print("  docker compose build")
print("  docker compose run eval-accuracy")
PYEOF