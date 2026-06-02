FROM python:3.11-slim
WORKDIR /eval
RUN apt-get update && apt-get install -y --no-install-recommends curl bash \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "evalscope[api]" || echo "evalscope optional"
COPY core/       ./core/
COPY tests/      ./tests/
COPY testcases/  ./testcases/
COPY datasets/   ./datasets/
COPY run.py      .
COPY run_evalscope.sh .
RUN chmod +x run_evalscope.sh && mkdir -p /reports
ENTRYPOINT ["python", "run.py", "--out", "/reports"]
