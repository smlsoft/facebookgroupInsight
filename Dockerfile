FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

# ติดตั้ง fonts ภาษาไทย
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-thai-tlwg \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ติดตั้ง Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY ai_scanner.py .
COPY db.py .
COPY config.json .

# สร้าง directories
RUN mkdir -p /app/output/screenshots

ENV PYTHONUNBUFFERED=1

CMD ["python", "ai_scanner.py"]
