# python:3.12.3-slim-bookworm (Debian 12, Python 3.12.3)
# Pinned by digest for reproducibility. Multi-arch (linux/amd64 + linux/arm64).
FROM python:3.12.3-slim-bookworm@sha256:afc139a0a640942491ec481ad8dda10f2c5b753f5c969393b12480155fe15a63

# Speed up: no .pyc files, no pip cache, no version-check chatter.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Non-root runtime user.
RUN groupadd --system app \
 && useradd --system --gid app --create-home --home-dir /home/app app

WORKDIR /app

# Resolve dependencies first (better layer caching).
# --require-hashes enforces cryptographic pinning from requirements.txt,
# so a compromised PyPI mirror cannot silently substitute bytes.
COPY requirements.txt /app/requirements.txt
RUN python -m pip --version \
 && python -m pip install --require-hashes -r requirements.txt

# Source last; image rebuilds reuse the deps layer when requirements.txt is unchanged.
COPY server.py /app/server.py
COPY templates /app/templates

# Default port + access code (override at runtime with -e ACCESS_CODE=... -p ...).
ENV ACCESS_CODE=changeMe
EXPOSE 5590

USER app
CMD ["python", "server.py", "--port", "5590"]
