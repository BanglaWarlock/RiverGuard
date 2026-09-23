# RiverGuard parser service
# Build:  docker build -t riverguard-parser parser/
# Run:    docker run --rm riverguard-parser
#
# NOTE: this image bakes parser/.env INTO the image (dev convenience).
# Because of that: never push or share this image, and remember that
# editing .env requires a rebuild before the change takes effect.

FROM python:3.11-slim

WORKDIR /app

# Dependencies first - this layer is cached, so rebuilding after a
# code change does NOT re-download packages.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now the code - INCLUDING .env (see note above; .dockerignore no
# longer excludes it).
COPY . .

# Fail the build loudly if .env is missing - a missing config file
# should be caught at BUILD time, not discovered at RUN time when the
# parser starts on defaults you didn't intend.
RUN test -f .env || (echo "ERROR: parser/.env not found - the parser refuses to build without its configuration." && exit 1)

# Run from /app so 'import state' etc. resolve - main.py's siblings
# are on the path because WORKDIR is the module root.
CMD ["python", "main.py"]