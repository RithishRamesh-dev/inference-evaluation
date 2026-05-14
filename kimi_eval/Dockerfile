FROM python:3.11-slim
WORKDIR /eval
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core/     ./core/
COPY sections/ ./sections/
COPY run.py    .
RUN mkdir -p /reports
ENTRYPOINT ["python", "run.py"]
