# RiverGuard parser service
# Run via the bat file or via compose

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Error log lands here - mount a volume to keep it on the host:
#   -v <host-dir>:/app/logs
RUN mkdir -p logs

CMD ["python", "main.py"]