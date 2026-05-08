FROM python:3.11-slim

WORKDIR /app

# 国内镜像加速：阿里云 apt（fallback debian default）
RUN (sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null \
     || sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list 2>/dev/null \
     || true)

# 仅装 fetcher / patenthub HTTP 抓取需要的最小系统依赖。
# 不装 chromium 系统包（libnss3/libxcomposite1/libxdamage1/libgbm1/libasound2/fonts-noto-cjk 等），
# 节省 ~150MB 系统包 + 165MB chromium 二进制 = ~315MB 镜像缩水。
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
        -r requirements.txt \
    && python -c "import httpx, fastapi, celery, sqlalchemy; print('sp-api deps OK')"

COPY . .

# 2026-05-08：sp-api 零本地 PDF 改造后，不再需要 /app/data/pdfs 目录
# （Celery worker 也不写文件了；fulltext_tasks 已 stub）。

EXPOSE 8000
