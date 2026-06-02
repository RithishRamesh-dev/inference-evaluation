#!/bin/bash
# Official evalscope runner — produces scores for 二、精度验收
set -e
API_URL="${EVAL_ENDPOINT_URL:?}" API_KEY="${EVAL_API_KEY:?}" MODEL="${EVAL_MODEL:-kimi-k2.6}"
MODE="${1:-smoke}"
OUT="./evalscope_results/$(date +%Y%m%d_%H%M%S)_${MODE}"
mkdir -p "$OUT"
THINK='{"extra_body":{"thinking":{"type":"enabled"}}}'
NOTHINK='{"extra_body":{"thinking":{"type":"disabled"}}}'
COMMON=(--eval-type openai_api --model "$MODEL" --api-url "$API_URL" --api-key "$API_KEY" --work-dir "$OUT")
case "$MODE" in
  smoke)   evalscope eval "${COMMON[@]}" --datasets aime25 ocr_bench mmmu_pro \
             --dataset-args '{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}' \
             --generation-config "$THINK" --limit 10 2>&1 | tee "$OUT/smoke.log" ;;
  think)   evalscope eval "${COMMON[@]}" --datasets aime25 ocr_bench mmmu_pro \
             --dataset-args '{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}' \
             --generation-config "$THINK" 2>&1 | tee "$OUT/think.log" ;;
  nothink) evalscope eval "${COMMON[@]}" --datasets aime25 ocr_bench mmmu_pro \
             --generation-config "$NOTHINK" 2>&1 | tee "$OUT/nothink.log" ;;
  all)     bash "$0" think && bash "$0" nothink ;;
  *) echo "Usage: $0 [smoke|think|nothink|all]"; exit 1 ;;
esac
echo "Done → $OUT"
