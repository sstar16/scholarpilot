FROM python:3.11-slim

WORKDIR /app

# 国内镜像加速：优先阿里云（稳定），清华作 fallback
RUN (sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null \
     || sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null \
     || true)

# 安装系统依赖（pdfplumber 需要 libpoppler + Playwright Chromium 需要一堆系统库）
RUN apt-get update && apt-get install -y \
    gcc \
    libpoppler-cpp-dev \
    poppler-utils \
    curl \
    # Playwright Chromium 运行依赖
    libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libxkbcommon0 libasound2 libx11-xcb1 libxtst6 \
    fonts-liberation fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 注意：不使用 --mount=type=cache，避免 cache mount 导致某些包未写入 image 层
# 国内加速：pip 走清华源；playwright chromium 独立 RUN + 失败容错（反爬 stealth 降级 fallback httpx）
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright
RUN pip install --no-cache-dir \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
        -r requirements.txt \
    && python -c "import duckdb, networkx, httpx, fastapi, celery, playwright; print('core deps OK')"

# Playwright Chromium 下载 ~165MB，国内 CDN 偶有 30s 超时；失败不阻塞 build。
# 运行期如需反爬 stealth 下载，可手动 docker exec <container> playwright install chromium 重试。
RUN playwright install chromium \
    || echo "[WARN] playwright chromium install failed; stealth fallback disabled until manual retry"

# Playwright Chromium 运行时补丁依赖（playwright install-deps 列表里必需但上面 apt 漏装的）
# 临时换到清华源避免 aliyun 被 TUN 代理拦截，需要的包都在 main 里
RUN (sed -i 's|mirrors.aliyun.com|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null \
     || sed -i 's|mirrors.aliyun.com|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true) \
    && for i in 1 2 3 4 5; do \
         apt-get update && apt-get install -y --fix-missing --no-install-recommends \
         libatspi2.0-0 libdrm2 libpango-1.0-0 libcairo2 libglib2.0-0 \
         libharfbuzz0b libfribidi0 libthai0 libgraphite2-3 \
         && break || { echo "apt retry $i/5"; sleep 5; }; \
       done \
    && apt-get install -y --fix-broken --no-install-recommends \
         libatspi2.0-0 libdrm2 libpango-1.0-0 libcairo2 libglib2.0-0 \
         libharfbuzz0b libfribidi0 libthai0 libgraphite2-3 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# 创建数据目录
RUN mkdir -p /app/data/pdfs /app/data/exports

EXPOSE 8000
