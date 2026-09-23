# RiverGuard API service
# Build:  docker build -t riverguard-api api/
# Run:    docker run --rm -p 8000:8000 riverguard-api
#
# NOTE: this image bakes api/.env INTO the image (dev convenience).
# Because of that: never push or share this image, and editing .env
# requires a rebuild before the change takes effect.

FROM python:3.11-slim

WORKDIR /app

# Dependencies first - this layer is cached, so rebuilding after a
# code change does NOT re-download packages.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now the code - INCLUDING .env (see note above).
COPY . .

# Fail the build loudly if .env is missing - a missing config file
# should be caught at BUILD time, not discovered at RUN time.
RUN test -f .env || (echo "ERROR: api/.env not found - the API refuses to build without its configuration." && exit 1)

# 8000 is what the outside world connects to (REST, /docs, /stream,
# and the website). -p 8000:8000 on 'docker run' maps onto this.
EXPOSE 8000

CMD ["python", "main.py"]