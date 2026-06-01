FROM python:3.11-slim

WORKDIR /eval

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl bash \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# evalscope for R11 accuracy benchmarks (optional but included)
RUN pip install --no-cache-dir "evalscope[api]" || echo "evalscope install failed — R11 full benchmarks unavailable"

# Copy project
COPY core/          ./core/
COPY tests/         ./tests/
COPY benchmarks/    ./benchmarks/
COPY testcases/     ./testcases/
COPY datasets/      ./datasets/
COPY run.py         .
COPY run_evalscope.sh .
RUN chmod +x run_evalscope.sh

# Reports written here — mount this volume
RUN mkdir -p /reports

ENTRYPOINT ["python", "run.py", "--out", "/reports"]