# CPU 専用の再利用可能な制作環境（GPU・有料サービス不要）。
# モデルはイメージに含めない（許可リスト経由で実行時に取得・検査し、/cache に保存）。
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    STUDIO_CACHE=/cache
RUN apt-get update && apt-get install -y --no-install-recommends clamav clamav-freshclam openssl git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements/ requirements/
RUN pip install -r requirements/base.txt && pip install -r requirements/gen.txt
COPY . .
RUN useradd -m studio && mkdir -p /cache && chown -R studio /cache /app
USER studio
CMD ["python", "-m", "studio", "doctor"]
