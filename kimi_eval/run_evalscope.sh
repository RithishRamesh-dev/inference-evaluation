#!/bin/bash
# run_evalscope.sh — Official evalscope benchmark runner for kimi-k2.6
# Run on the droplet: bash run_evalscope.sh
#
# Prerequisites:
#   pip install evalscope[api]
#   export EVAL_API_KEY=your-api-key
#
# Usage:
#   bash run_evalscope.sh smoke    # 10 samples, think=on (fast validation)
#   bash run_evalscope.sh think    # full run, think=on
#   bash run_evalscope.sh nothink  # full run, think=off
#   bash run_evalscope.sh all      # full run, both modes (spec-compliant)

set -e

API_URL="https://inference.do-ai.run/v1"
MODEL="kimi-k2.6"
API_KEY="${EVAL_API_KEY:?'Set EVAL_API_KEY env var'}"

MODE="${1:-smoke}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="./evalscope_results/${TIMESTAMP}_${MODE}"
mkdir -p "$OUTPUT_DIR"

echo "======================================================"
echo "  evalscope benchmark runner"
echo "  Mode      : $MODE"
echo "  Model     : $MODEL"
echo "  Endpoint  : $API_URL"
echo "  Output    : $OUTPUT_DIR"
echo "======================================================"

# ── Common args ───────────────────────────────────────────────────────────────
COMMON_ARGS=(
  --eval-type openai_api
  --model "$MODEL"
  --api-url "$API_URL"
  --api-key "$API_KEY"
  --work-dir "$OUTPUT_DIR"
)

THINK_CONFIG='{"extra_body":{"enable_thinking":true}}'
NOTHINK_CONFIG='{"extra_body":{"enable_thinking":false}}'

MMMU_VISION='{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}'
MMMU_STANDARD='{"mmmu_pro":{}}'

# ── Mode selection ────────────────────────────────────────────────────────────
case "$MODE" in

  smoke)
    echo ""
    echo ">>> SMOKE TEST: 10 samples, think=on, all 3 benchmarks"
    evalscope eval "${COMMON_ARGS[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --dataset-args "$MMMU_VISION" \
      --generation-config "$THINK_CONFIG" \
      --limit 10 \
      2>&1 | tee "$OUTPUT_DIR/smoke_think.log"
    ;;

  think)
    echo ""
    echo ">>> FULL RUN: think=on — OCRBench, AIME25, MMMU Pro Vision"
    echo "    Expected: OCRBench=91%, AIME25=98.4%, MMMU Pro=78.8%"
    evalscope eval "${COMMON_ARGS[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --dataset-args "$MMMU_VISION" \
      --generation-config "$THINK_CONFIG" \
      2>&1 | tee "$OUTPUT_DIR/think_full.log"
    ;;

  nothink)
    echo ""
    echo ">>> FULL RUN: think=off — OCRBench, AIME25, MMMU Pro"
    echo "    Expected: OCRBench=92%, AIME25=70.5%, MMMU Pro=74.9%"
    evalscope eval "${COMMON_ARGS[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --dataset-args "$MMMU_STANDARD" \
      --generation-config "$NOTHINK_CONFIG" \
      2>&1 | tee "$OUTPUT_DIR/nothink_full.log"
    ;;

  all)
    echo ""
    echo ">>> FULL SPEC-COMPLIANT RUN: both think modes"

    echo ""
    echo "--- Pass 1/2: think=on ---"
    evalscope eval "${COMMON_ARGS[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --dataset-args "$MMMU_VISION" \
      --generation-config "$THINK_CONFIG" \
      2>&1 | tee "$OUTPUT_DIR/think_full.log"

    echo ""
    echo "--- Pass 2/2: think=off ---"
    evalscope eval "${COMMON_ARGS[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --dataset-args "$MMMU_STANDARD" \
      --generation-config "$NOTHINK_CONFIG" \
      2>&1 | tee "$OUTPUT_DIR/nothink_full.log"
    ;;

  *)
    echo "Usage: $0 [smoke|think|nothink|all]"
    exit 1
    ;;
esac

echo ""
echo "======================================================"
echo "  Done. Results in: $OUTPUT_DIR"
echo "======================================================"
