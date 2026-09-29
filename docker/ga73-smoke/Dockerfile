# Trusted evaluation image. No corpus Dockerfile/setup.py is evaluated here.
# CI supplies a registry-resolved immutable official Python base.
ARG PYTHON_BASE
FROM ${PYTHON_BASE}
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --only-binary=:all: pytest==8.3.4 pytest-timeout==2.3.1 \
    && python -I -c 'import pytest'
USER 65534:65534
WORKDIR /workspace
