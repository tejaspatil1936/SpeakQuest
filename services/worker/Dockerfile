# syntax=docker/dockerfile:1.7
#
# SpeakQuest analysis worker — AWS Lambda container image (system design §4).
# Python 3.12 + numpy/scipy/parselmouth/pydantic + a static ffmpeg/ffprobe.
# No PyTorch. Build from the repository root:
#
#   docker build -f services/worker/Dockerfile -t speakquest-worker .

ARG LAMBDA_PYTHON=public.ecr.aws/lambda/python:3.12

# ---------------------------------------------------------------- ffmpeg
FROM public.ecr.aws/docker/library/debian:bookworm-slim AS ffmpeg
# Pinned static build; the checksum was recorded when the pin was chosen
# (the upstream archive publishes no checksum for old releases).
ARG FFMPEG_VERSION=6.0.1
ARG FFMPEG_SHA256=28268bf402f1083833ea269331587f60a242848880073be8016501d864bd07a5
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL --retry 3 -o /tmp/ffmpeg.tar.xz \
      "https://johnvansickle.com/ffmpeg/old-releases/ffmpeg-${FFMPEG_VERSION}-amd64-static.tar.xz" \
 && echo "${FFMPEG_SHA256}  /tmp/ffmpeg.tar.xz" | sha256sum -c - \
 && mkdir -p /out \
 && tar -xJf /tmp/ffmpeg.tar.xz -C /tmp \
 && cp /tmp/ffmpeg-${FFMPEG_VERSION}-amd64-static/ffmpeg \
       /tmp/ffmpeg-${FFMPEG_VERSION}-amd64-static/ffprobe /out/

# ---------------------------------------------------------------- python deps
FROM ${LAMBDA_PYTHON} AS deps
# Exact versions and hashes from uv.lock (exported by scripts/build-worker.sh).
COPY build/worker-requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: \
      --target /deps -r /tmp/requirements.txt

# ---------------------------------------------------------------- runtime
FROM ${LAMBDA_PYTHON}
COPY --from=ffmpeg /out/ /opt/bin/
COPY --from=deps /deps ${LAMBDA_TASK_ROOT}
COPY services/worker/speakquest ${LAMBDA_TASK_ROOT}/speakquest
COPY services/api/speakquest_api ${LAMBDA_TASK_ROOT}/speakquest_api
COPY services/explain/speakquest_explain ${LAMBDA_TASK_ROOT}/speakquest_explain
COPY rubric/v1.yaml ${LAMBDA_TASK_ROOT}/rubric/v1.yaml
RUN rm -rf ${LAMBDA_TASK_ROOT}/speakquest_api/local \
 && python -c "import speakquest_api.worker_steps, parselmouth, scipy, numpy" \
 && /opt/bin/ffmpeg -hide_banner -version | head -1

ENV SPEAKQUEST_RUBRIC=${LAMBDA_TASK_ROOT}/rubric/v1.yaml \
    SPEAKQUEST_FFMPEG=/opt/bin/ffmpeg \
    SPEAKQUEST_FFPROBE=/opt/bin/ffprobe

CMD ["speakquest_api.lambdas.worker_handler"]
