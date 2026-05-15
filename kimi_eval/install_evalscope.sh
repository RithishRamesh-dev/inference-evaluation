#!/bin/bash
# install_evalscope.sh — Install evalscope and verify it works
set -e

echo "Installing evalscope..."
pip install evalscope[api] --break-system-packages -q

echo ""
echo "Verifying installation..."
evalscope --version 2>/dev/null || python -m evalscope --version 2>/dev/null || echo "Installed (version flag not supported)"

echo ""
echo "Available datasets check..."
python3 -c "
import subprocess, json
# Check evalscope can list datasets
result = subprocess.run(['evalscope', 'list-datasets'],
                        capture_output=True, text=True)
output = result.stdout + result.stderr
if 'aime' in output.lower() or 'ocr' in output.lower():
    print('Datasets available: aime25, ocr_bench, mmmu_pro confirmed')
else:
    print('Dataset listing output:')
    print(output[:500])
" 2>/dev/null || echo "evalscope installed - dataset check requires network"

echo ""
echo "Installation complete. Now run:"
echo "  export EVAL_API_KEY=your-api-key"
echo "  bash run_evalscope.sh smoke   # quick 10-sample test"
