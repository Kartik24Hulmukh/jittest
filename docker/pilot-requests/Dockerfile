# Option C trusted runtime image for the requests/Flask pilot.
# Contract: docs/RUNTIME-IMAGES.md. Pinned by digest when referenced from
# [tool.jittest.runtime]; rebuilt only through CI so the digest is reproducible.
# No candidate bytes ever enter this image: the checkout is bind-mounted at
# /workspace read-write and jittest itself read-only at /opt/jittest.
# PIN BEFORE USE: replace the tag with the digest printed by
#   docker buildx imagetools inspect python:3.12-slim
# The RUNTIME-IMAGES.md contract requires an @sha256 digest; a floating tag is
# accepted only for local builds and is rejected by [tool.jittest.runtime].
FROM python:3.12-slim
LABEL org.opencontainers.image.title="jittest-pilot-requests" \
      org.opencontainers.image.description="Pinned pytest + requests + Flask runtime for isolated candidate execution" \
      org.opencontainers.image.source="https://github.com/Kartik24Hulmukh/jittest"
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir --only-binary :all: \
      pytest==8.3.4 pytest-timeout==2.3.1 requests==2.32.3 flask==3.1.0 \
    && python -c "import pytest, requests, flask"
USER 65534:65534
WORKDIR /workspace
