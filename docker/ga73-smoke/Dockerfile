# Trusted evaluation image. No corpus Dockerfile/setup.py is evaluated here.
# CI supplies a registry-resolved immutable official Python 3.8 base.
# Historical BugsInPy specimens require 3.8; Jittest host remains Python 3.12.
# Legacy runtime is research-only, offline and confined, NOT a production recommendation.
ARG PYTHON_BASE
FROM ${PYTHON_BASE}
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --only-binary=:all: pytest==8.3.4 pytest-timeout==2.3.1 \
    decorator==4.4.2 future==1.0.0 six==1.16.0 \
    && python -I -c 'import pytest'
USER 65534:65534
WORKDIR /workspace
