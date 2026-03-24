FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（pdfplumber 需要 libpoppler）
RUN apt-get update && apt-get install -y \
    gcc \
    libpoppler-cpp-dev \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

# 创建数据目录
RUN mkdir -p /app/data/pdfs /app/data/exports

EXPOSE 8000
