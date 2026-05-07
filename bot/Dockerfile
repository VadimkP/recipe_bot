FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source
COPY . .

# Data directory for SQLite
RUN mkdir -p /data

CMD ["python", "main.py"]
