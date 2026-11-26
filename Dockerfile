# 共通制作イメージ（CPU 専用）: Python + PyTorch(CPU) + Diffusers + Transformers + ClamAV
# - ライブラリは固定版（requirements/lock-cpu.txt）。毎回の pip install を不要にする。
# - モデル本体は含めない（許可リスト → 取得 → ClamAV → SHA256 → actions/cache で別管理）。
# - リポジトリのコードも含めない（実行時に /work へマウント）。コード変更でイメージを作り直さないため。
FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/koda24-cell/koda24-cell-illustration-ai-studio"
LABEL org.opencontainers.image.description="Illustration AI Studio shared CPU runtime (PyTorch/Diffusers/ClamAV, no models)"
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    STUDIO_CACHE=/work/.cache/studio
RUN apt-get update \
    && apt-get install -y --no-install-recommends clamav clamav-freshclam openssl git ca-certificates \
    && sed -i -E '/^[[:space:]]*NotifyClamd[[:space:]]/d' /etc/clamav/freshclam.conf \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/clamav && chown clamav:clamav /var/lib/clamav
COPY requirements/base.txt requirements/lock-cpu.txt /tmp/req/
RUN pip install -r /tmp/req/base.txt && pip install -r /tmp/req/lock-cpu.txt \
    && python -c "import torch, diffusers, transformers; print('torch', torch.__version__, 'diffusers', diffusers.__version__, 'transformers', transformers.__version__)"
# 定義DBの初期値（実行時の freshclam は差分更新だけで済む）。取得失敗時も実行時に必ず更新・検査する
RUN (freshclam --stdout || echo "freshclam at build failed; runtime update is mandatory") && chmod -R a+rX /var/lib/clamav
WORKDIR /work
CMD ["python", "-m", "studio", "doctor"]
