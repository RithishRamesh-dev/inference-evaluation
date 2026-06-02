FROM python:3.11-slim
WORKDIR /eval
RUN apt-get update && apt-get install -y --no-install-recommends curl bash git \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core/       ./core/
COPY tests/      ./tests/
COPY testcases/  ./testcases/
COPY datasets/   ./datasets/
COPY run.py      .
RUN mkdir -p /reports outputs
ENTRYPOINT ["python", "run.py", "--out", "/reports"]