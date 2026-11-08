# syntax=docker/dockerfile:1.7
FROM python:3.10.19-slim-bookworm@sha256:23f63358922e79a794f71be8f3723c84e5ccca9638af3f74456dc73d6184499e AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY requirements.lock ./
RUN pip install pip==25.1.1 setuptools==80.9.0 wheel==0.45.1 \
    && pip install --require-hashes -r requirements.lock
COPY scripts/install_melo.py ./install_melo.py
RUN python install_melo.py
# Required by g2p_en at import/inference; avoid downloads into an immutable image.
RUN python -m nltk.downloader -d /opt/nltk_data cmudict averaged_perceptron_tagger \
    && test -f /opt/nltk_data/corpora/cmudict/cmudict \
    && test -f /opt/nltk_data/taggers/averaged_perceptron_tagger/averaged_perceptron_tagger.pickle

FROM python:3.10.19-slim-bookworm@sha256:23f63358922e79a794f71be8f3723c84e5ccca9638af3f74456dc73d6184499e AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 speech \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /data speech \
    && mkdir -p /data/hf /data/cache /data/cache/numba \
    && chown -R 10001:10001 /data
COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/nltk_data /opt/nltk_data
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data HF_HOME=/data/hf XDG_CACHE_HOME=/data/cache \
    NUMBA_CACHE_DIR=/data/cache/numba NLTK_DATA=/opt/nltk_data \
    OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false \
    HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
WORKDIR /srv
COPY app ./app
COPY requirements.lock /srv/requirements.lock
USER 10001:10001
VOLUME ["/data/hf", "/data/cache"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30m --retries=4 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/health/ready', timeout=2)"]
CMD ["python", "-m", "app.main"]
