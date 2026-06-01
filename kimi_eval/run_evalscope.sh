#!/bin/bash
# run_evalscope.sh — Official evalscope benchmark runner
# Uses Anthropic-style thinking format as required by spec.
set -e
API_URL="${EVAL_ENDPOINT_URL:?Set EVAL_ENDPOINT_URL}"
API_KEY="${EVAL_API_KEY:?Set EVAL_API_KEY}"
MODEL="${EVAL_MODEL:-kimi-k2.6}"
MODE="${1:-smoke}"
TS=$(date +%Y%m%d_%H%M%S)
OUTDIR="./evalscope_results/${TS}_${MODE}"
mkdir -p "$OUTDIR"

# Anthropic-style thinking format per spec
THINK='{"extra_body":{"thinking":{"type":"enabled"}}}'
NOTHINK='{"extra_body":{"thinking":{"type":"disabled"}}}'

COMMON=(--eval-type openai_api --model "$MODEL" --api-url "$API_URL" --api-key "$API_KEY" --work-dir "$OUTDIR")

echo "======================================"
echo "  evalscope | mode=$MODE | model=$MODEL"
echo "======================================"

case "$MODE" in
  smoke)
    echo ">>> SMOKE (10 samples, think=on)"
    evalscope eval "${COMMON[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --dataset-args '{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}' \
      --generation-config "$THINK" --limit 10 \
      2>&1 | tee "$OUTDIR/smoke_think.log"
    ;;
  think)
    echo ">>> FULL think=on: OCR=91% AIME=98.4% MMMU=78.8%"
    evalscope eval "${COMMON[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --dataset-args '{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}' \
      --generation-config "$THINK" 2>&1 | tee "$OUTDIR/think.log"
    ;;
  nothink)
    echo ">>> FULL think=off: OCR=92% AIME=70.5% MMMU=74.9%"
    evalscope eval "${COMMON[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --generation-config "$NOTHINK" 2>&1 | tee "$OUTDIR/nothink.log"
    ;;
  all)
    echo ">>> FULL both modes"
    evalscope eval "${COMMON[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --dataset-args '{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}' \
      --generation-config "$THINK" 2>&1 | tee "$OUTDIR/think.log"
    evalscope eval "${COMMON[@]}" \
      --datasets aime25 ocr_bench mmmu_pro \
      --generation-config "$NOTHINK" 2>&1 | tee "$OUTDIR/nothink.log"
    ;;
  *) echo "Usage: $0 [smoke|think|nothink|all]"; exit 1 ;;
esac
echo "Results: $OUTDIR"