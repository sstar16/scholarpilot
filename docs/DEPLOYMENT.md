# ScholarPilot 服务器部署运维手册

> 本手册面向计算机专业本科生，假设你会用命令行，但没有服务器运维经验。
> 每条命令都会解释"为什么这样做"，遇到问题先查第 8 章。

---

## 0. 阅读前须知

### 符号约定

- `$` 开头：在**服务器**终端执行的命令（不要输入 `$` 本身）
- `>` 开头：在**本地电脑**终端执行
- `<YOUR_XXX>`：替换成你自己的值，尖括号也不要
- `# 注释`：说明文字，不用输入

### 你需要准备的东西

- [ ] 一台 VPS（见第 1 章怎么选）
- [ ] 一个域名，已转入 Cloudflare 管理（选做，不用域名也能跑）
- [ ] 项目代码在 GitHub 上有仓库
- [ ] SSH 客户端（Windows 推荐 Windows Terminal 或 MobaXTerm）

### 整体架构（两套环境并行）

```
外网用户
  └─ Cloudflare CDN（HTTPS 443）
      └─ 服务器 Nginx（监听 80 / 443）
          └─ 生产环境（/opt/scholarpilot/prod/）
              ├─ frontend  容器（内部 :80）
              ├─ backend   容器（内部 :8000）
              ├─ worker    容器（Celery 任务处理）
              ├─ beat      容器（Celery 定时任务）
              ├─ flower    容器（内部 :5555，不对外）
              ├─ postgres  容器（内部 :5432）
              └─ redis     容器（内部 :6379）

你（开发者）通过 SSH 隧道访问：
  > ssh -L 8080:localhost:8080 deploy@<服务器IP>
  └─ 开发环境（/opt/scholarpilot/dev/）
      └─ 同样一套服务，nginx 监听 8080（不对外暴露）
```

### 两套环境端口速查

| 环境 | 前端访问 | Flower 监控 | Docker 卷 |
|------|---------|------------|---------|
| 生产（prod） | `:80` / `:443` | `:5555`（不对外） | `prod_pgdata` |
| 开发（dev） | `:8080`（SSH 隧道） | `:5556`（SSH 隧道） | `dev_pgdata` |

> 两套环境的数据库卷完全独立，互不干扰。

---

## 1. 服务器选购建议

### 1.1 推荐配置

| 项目 | 最低配置 | 推荐配置 | 备注 |
|------|---------|---------|------|
| CPU | 2 核 | 2 核 | 瓶颈在 I/O，CPU 不需要太高 |
| 内存 | 2 GB | **4 GB** | pg + pgvector + 4 个 Celery worker 约 1.5 GB，2 GB 太紧 |
| 磁盘 | 20 GB SSD | 40 GB SSD | Docker 镜像约 5 GB，PDF 存储按需 |
| 带宽 | 3 Mbps | 5 Mbps | 文献检索是 I/O 密集型 |
| 系统 | Ubuntu 22.04 LTS | **Ubuntu 22.04 LTS** | 不选 24.04，部分包兼容性差 |

### 1.2 厂商推荐

| 场景 | 推荐厂商 | 参考价格 | 备注 |
|------|---------|---------|------|
| 国内用户访问 | 阿里云 ECS / 腾讯云 CVM | 学生机 99 元/年 | **需要 ICP 备案**（见下文） |
| 海外用户 / 不想备案 | 搬瓦工 / Vultr / DigitalOcean | $5-10/月 | 不需要备案，香港节点国内也能访问 |

### 1.3 关于 ICP 备案

国内服务器（阿里云/腾讯云）如果用域名直接访问，必须 ICP 备案。
- 备案周期：7-14 天
- 备案期间：只能用 IP 访问，或者先用 Cloudflare Tunnel 过渡
- 阿里云/腾讯云都提供免费备案服务，控制台搜"备案"即可

---

## 2. 服务器初始化（只做一次）

SSH 登录服务器后，按顺序执行以下步骤。

### 2.1 创建普通用户

为什么：长期用 root 操作有误删系统文件的风险，创建一个普通用户更安全。

```bash
# 登录后先切到 root（如果 VPS 给的是 root 账号）
# 创建 deploy 用户，加入 sudo 组
$ adduser deploy
$ usermod -aG sudo deploy

# 切换到新用户，后续操作都用 deploy
$ su - deploy
```

### 2.2 配置 SSH 密钥登录

为什么：密码登录容易被暴力破解，密钥登录更安全，还省去每次输密码的麻烦。

```bash
# 在【本地电脑】生成密钥对（如果已有 ~/.ssh/id_ed25519 可跳过）
> ssh-keygen -t ed25519 -C "scholarpilot"

# 把公钥上传到服务器
> ssh-copy-id deploy@<服务器IP>

# 测试密钥登录是否成功（不用输密码就能登录说明成功）
> ssh deploy@<服务器IP>
```

配置好密钥后，禁用密码登录（可选但推荐）：

```bash
$ sudo nano /etc/ssh/sshd_config
# 找到下面这行，改为 no
# PasswordAuthentication yes  →  PasswordAuthentication no

$ sudo systemctl reload sshd
```

> ⚠️ 禁用密码前，先确认密钥登录可以成功，否则会把自己锁在门外。

### 2.3 配置防火墙

为什么：只开放必要端口，减少被攻击的面。开发端口（8080/5556）不对外开放，用 SSH 隧道访问。

```bash
$ sudo ufw allow OpenSSH     # SSH 连接，必须开，不然锁死自己
$ sudo ufw allow 80/tcp      # HTTP
$ sudo ufw allow 443/tcp     # HTTPS
$ sudo ufw enable
$ sudo ufw status            # 确认规则生效
```

### 2.4 安装 Docker

为什么：ScholarPilot 所有服务都跑在 Docker 容器里，Docker 是核心依赖。

```bash
# 官方安装脚本（国内可能慢，备用方案见下）
$ curl -fsSL https://get.docker.com | sudo sh

# 国内服务器备用：用阿里云镜像安装
$ curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
$ echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
    https://mirrors.aliyun.com/docker-ce/linux/ubuntu jammy stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list
$ sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 把 deploy 用户加入 docker 组（避免每次都要 sudo）
$ sudo usermod -aG docker $USER
$ newgrp docker   # 立即生效，不用重新登录

# 验证
$ docker --version
$ docker compose version
```

### 2.5 配置 Docker 国内镜像加速

为什么：不配置的话从 Docker Hub 拉镜像极慢甚至超时，国内服务器必须配。

```bash
$ sudo mkdir -p /etc/docker
$ sudo tee /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://registry.cn-hangzhou.aliyuncs.com",
    "https://mirror.ccs.tencentyun.com"
  ]
}
EOF
$ sudo systemctl daemon-reload && sudo systemctl restart docker
```

### 2.6 安装 Git

```bash
$ sudo apt-get update && sudo apt-get install -y git
$ git --version
```

---

## 3. 首次部署生产环境

### 3.1 目录规划

```bash
$ sudo mkdir -p /opt/scholarpilot/{prod,dev,backups}
$ sudo chown -R deploy:deploy /opt/scholarpilot
```

目录说明：
- `prod/`：生产环境代码，客户访问这里
- `dev/`：开发环境代码，自己测试用
- `backups/`：数据库备份文件

### 3.2 拉取生产代码

```bash
$ cd /opt/scholarpilot
$ git clone https://github.com/<你的账号>/scholarpilot.git prod
$ cd prod
```

### 3.3 配置环境变量

```bash
$ cp .env.example .env
$ nano .env
```

**必须修改**的变量（其余保持默认即可）：

| 变量 | 怎么填 | 示例 |
|------|-------|------|
| `POSTGRES_PASSWORD` | 用下面命令生成 | `a3f8c2...`（随机32位） |
| `SECRET_KEY` | 用下面命令生成 | `b9d1e4...`（随机32位） |
| `DATABASE_URL` | 密码部分替换成上面的 `POSTGRES_PASSWORD` | `postgresql+asyncpg://urip:<密码>@postgres:5432/urip` |
| `DEBUG` | 改为 `false` | `false` |
| `UNPAYWALL_EMAIL` | 你的邮箱 | `your@email.com` |

生成随机密码的命令：
```bash
$ openssl rand -hex 32
# 复制输出，粘贴到 .env 对应位置
```

### 3.4 创建数据目录

为什么：docker-compose.yml 把 `./data/pdfs` 和 `./data/exports` 挂载进容器，目录不存在容器会报错。

```bash
$ mkdir -p data/pdfs data/exports
```

### 3.5 构建并启动

```bash
# 先拉取不需要构建的基础镜像（postgres、redis、nginx）
$ docker compose pull postgres redis nginx

# 构建需要 Dockerfile 的镜像（backend、worker、beat、flower、frontend）
# 第一次构建较慢（10-20分钟），后续增量构建很快
$ docker compose build

# 后台启动所有服务
$ docker compose up -d
```

### 3.6 验证部署结果

```bash
# 查看所有容器状态，都应该是 Up（不能有 Exit 或 Restarting）
$ docker compose ps

# 确认数据库迁移成功
$ docker compose logs backend | grep -i "alembic"
# 正常输出：Running upgrade ... -> ..., add_xxx

# 确认后端响应
$ curl http://localhost/api/health
# 或者
$ curl -I http://localhost
# 应该返回 HTTP/1.1 200 OK

# 实时查看日志（Ctrl+C 退出，服务继续跑）
$ docker compose logs -f backend
```

---

## 4. 开发环境隔离（同台服务器）

### 4.1 为什么要隔离

生产环境跑着客户的数据，不能用来测新功能。开发环境让你随便折腾，坏了也不影响客户。

隔离的核心手段：两个独立目录 → Docker 项目名不同 → **数据卷自动隔离**。

> Docker Compose 默认用目录名作为项目名。`prod/` 目录的卷叫 `prod_pgdata`，`dev/` 目录的卷叫 `dev_pgdata`，天然不同，数据不会串。

### 4.2 克隆开发代码

```bash
$ cd /opt/scholarpilot
$ git clone https://github.com/<你的账号>/scholarpilot.git dev
$ cd dev

# 切到开发分支
$ git checkout feat/phase2-revision-knowledge
```

### 4.3 创建端口 override 文件

为什么：生产环境已经占用了 80 和 5555 端口，开发环境要用不同端口避免冲突。创建 override 文件而不是改 docker-compose.yml，这样不会影响 git 仓库。

```bash
$ cat > docker-compose.override.yml <<'EOF'
# 开发环境端口覆盖（此文件不要提交到 git）
services:
  nginx:
    ports:
      - "8080:80"
  flower:
    ports:
      - "5556:5555"
EOF
```

### 4.4 配置开发环境变量

```bash
$ cp .env.example .env
$ nano .env
# 同样修改 POSTGRES_PASSWORD、SECRET_KEY、DATABASE_URL
# 密码可以和生产不同（建议不同）
$ mkdir -p data/pdfs data/exports
```

### 4.5 启动开发环境

```bash
$ docker compose build
$ docker compose up -d
$ docker compose ps   # 确认都是 Up
```

### 4.6 从本地访问开发环境

开发端口（8080）不对外开放（防火墙没开），用 SSH 隧道安全访问：

```bash
# 在本地电脑执行（保持这个窗口开着）
> ssh -L 8080:localhost:8080 -L 5556:localhost:5556 deploy@<服务器IP>
```

然后本地浏览器打开 `http://localhost:8080` 即可访问服务器上的开发环境。

原理：SSH 把本地 8080 端口的流量加密转发到服务器的 8080 端口，等于在本地访问服务器内网。

---

## 5. 域名 + HTTPS 配置

> 如果暂时不需要域名，可以直接用 IP 访问，跳过本章。

### 5.1 Cloudflare DNS 配置

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com)
2. 选择你的域名 → DNS → 添加记录
3. 类型选 `A`，名称填 `scholarpilot`（或其他子域名），IPv4 填服务器公网 IP
4. 代理状态先选**灰色（仅 DNS）**，等 HTTPS 配好后再开启橙色代理

> 橙色（CDN 代理）= 流量走 Cloudflare，有 DDoS 防护和 CDN 加速，隐藏真实 IP。
> 灰色（仅 DNS）= 直接解析到服务器 IP，调试方便。
> 建议先用灰色测通，再开橙色。

### 5.2 申请免费 SSL 证书（Let's Encrypt）

```bash
$ sudo apt-get install -y certbot

# ⚠️ 申请证书时 certbot 需要占用 80 端口，先停 nginx
$ docker compose stop nginx

# 申请证书（把域名替换成你的）
$ sudo certbot certonly --standalone \
    -d scholarpilot.yourdomain.com \
    --email your@email.com \
    --agree-tos --non-interactive

# 证书文件位置
# /etc/letsencrypt/live/scholarpilot.yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/scholarpilot.yourdomain.com/privkey.pem
```

### 5.3 修改 nginx 配置支持 HTTPS

编辑 `nginx/nginx.conf`，把原来的单个 server 块替换为：

```nginx
events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    keepalive_timeout 65;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript;

    upstream backend {
        server backend:8000;
    }

    upstream frontend {
        server frontend:80;
    }

    # HTTP → HTTPS 重定向
    server {
        listen 80;
        server_name scholarpilot.yourdomain.com;
        return 301 https://$host$request_uri;
    }

    # HTTPS 主服务
    server {
        listen 443 ssl;
        server_name scholarpilot.yourdomain.com;
        client_max_body_size 50M;

        ssl_certificate     /etc/letsencrypt/live/scholarpilot.yourdomain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/scholarpilot.yourdomain.com/privkey.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;

        location /api/ {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_read_timeout 3600s;
        }

        location /ws/ {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_read_timeout 3600s;
        }

        location /docs {
            proxy_pass http://backend;
            proxy_set_header Host $host;
        }

        location /openapi.json {
            proxy_pass http://backend;
            proxy_set_header Host $host;
        }

        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
        }
    }
}
```

### 5.4 修改 docker-compose.yml 挂载证书

在 `docker-compose.yml` 的 nginx 服务里添加证书 volume 和 443 端口：

```yaml
  nginx:
    image: nginx:1.25-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"          # 新增
    depends_on:
      - backend
      - frontend
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro   # 新增：挂载证书目录
```

重启 nginx：

```bash
$ docker compose up -d nginx
$ curl -I https://scholarpilot.yourdomain.com
# 应返回 HTTP/2 200
```

### 5.5 配置证书自动续期

Let's Encrypt 证书 90 天有效，需要自动续期：

```bash
# 测试续期流程
$ sudo certbot renew --dry-run

# 配置 cron（每月 1 日凌晨 3:00 执行）
$ (crontab -l 2>/dev/null; echo "0 3 1 * * certbot renew --quiet && /usr/bin/docker compose -f /opt/scholarpilot/prod/docker-compose.yml restart nginx") | crontab -l
```

---

## 6. 更新生产版本（日常最常用）

### 6.0 每次更新的第一步

```bash
$ cd /opt/scholarpilot/prod
$ git pull origin main   # 拉取最新代码（把 main 改成你的生产分支名）
```

### 6.1 根据改动类型选择命令

| 改了什么 | 需要重新 build？ | 执行命令 | 约耗时 |
|----------|---------------|---------|-------|
| Python 代码（`app/` 目录） | **否** | `docker compose restart backend worker beat` | <30 秒 |
| `requirements.txt` | **是** | `docker compose build backend worker beat flower && docker compose up -d` | 3-5 分钟 |
| 前端代码（Vue 组件/样式） | **是** | `docker compose build frontend && docker compose up -d frontend && docker compose restart nginx` | 2-3 分钟 |
| 数据库新增字段（migration） | **否** | 先备份，再 `docker compose restart backend` | <1 分钟 |
| `.env` 环境变量 | **否** | `docker compose up -d backend worker beat flower && docker compose restart nginx` | <30 秒 |

> ⚠️ **重要**：容器被 `up -d` 重建后 IP 会变化，nginx 必须 restart 刷新 DNS 缓存，否则出现 502 错误。这是一个常见坑。

---

### 详细流程：只改了 Python 后端代码

```bash
$ git pull origin main
$ docker compose restart backend worker beat

# 确认重启成功
$ docker compose ps
$ docker compose logs backend --tail=20
```

原理：`docker-compose.yml` 里 `./backend/app:/app/app` 是 volume 挂载，宿主机代码更新后容器内立刻生效，不需要重建镜像。

---

### 详细流程：改了前端代码

```bash
$ git pull origin main
$ docker compose build frontend
$ docker compose up -d frontend   # 用新镜像替换旧容器
$ docker compose restart nginx    # 刷新 nginx DNS 缓存（必须）

# 验证
$ curl -I http://localhost
```

原理：前端代码在 Dockerfile 里 `npm run build`，打包进镜像，没有 volume 挂载，所以改了必须重新构建镜像。

---

### 详细流程：新增了数据库字段（migration）

```bash
# 第一步：备份（别省这步，出问题能回滚）
$ /opt/scholarpilot/scripts/backup.sh

# 第二步：拉代码
$ git pull origin main

# 第三步：重启 backend（启动时自动执行 alembic upgrade head）
$ docker compose restart backend

# 第四步：确认迁移成功
$ docker compose logs backend --tail=30 | grep -i alembic
# 正常输出：Running upgrade 0003 -> 0004, add_xxx_column
```

如果迁移失败（backend 反复重启），恢复备份见第 7 章。

---

## 7. 数据库备份与恢复

### 7.1 手动备份（随时执行）

```bash
$ docker compose exec postgres pg_dump \
    -U urip \
    -Fc \
    urip \
    > /opt/scholarpilot/backups/manual_$(date +%Y%m%d_%H%M%S).dump

# -Fc 是自定义格式，比纯 SQL 小很多，支持并行恢复
```

### 7.2 恢复备份

```bash
# 停止依赖数据库的服务（避免恢复时有连接冲突）
$ docker compose stop backend worker beat flower

# 恢复（把文件名替换成实际备份文件）
$ docker compose exec -T postgres pg_restore \
    -U urip \
    -d urip \
    --clean --if-exists \
    < /opt/scholarpilot/backups/manual_20260101_120000.dump

# 重启服务
$ docker compose start backend worker beat flower

# 确认恢复成功
$ docker compose logs backend --tail=20
```

### 7.3 自动备份脚本

执行以下命令创建备份脚本：

```bash
$ mkdir -p /opt/scholarpilot/scripts
$ cat > /opt/scholarpilot/scripts/backup.sh <<'EOF'
#!/bin/bash
set -e

BACKUP_DIR="/opt/scholarpilot/backups"
COMPOSE_DIR="/opt/scholarpilot/prod"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/auto_$DATE.dump"

echo "[$(date)] 开始备份..."

# 执行备份
docker compose -f "$COMPOSE_DIR/docker-compose.yml" exec -T postgres \
    pg_dump -U urip -Fc urip > "$BACKUP_FILE"

echo "[$(date)] 备份完成：$BACKUP_FILE ($(du -sh $BACKUP_FILE | cut -f1))"

# 删除 30 天前的旧备份
find "$BACKUP_DIR" -name "auto_*.dump" -mtime +30 -delete
echo "[$(date)] 已清理 30 天前的旧备份"
EOF
$ chmod +x /opt/scholarpilot/scripts/backup.sh
```

配置每日自动执行：

```bash
# 每天凌晨 3:00 自动备份
$ (crontab -l 2>/dev/null; echo "0 3 * * * /opt/scholarpilot/scripts/backup.sh >> /var/log/scholarpilot-backup.log 2>&1") | crontab -

# 验证 cron 已添加
$ crontab -l
```

### 7.4 备份文件异地存储（推荐）

把备份文件下载到本地电脑，防止服务器硬盘损坏：

```bash
# 在本地电脑执行
> scp deploy@<服务器IP>:/opt/scholarpilot/backups/auto_20260101_030000.dump ~/Downloads/
```

---

## 8. 常见问题排查

### 排查的通用方法

```bash
# 第一步：看所有容器状态
$ docker compose ps

# 第二步：看出问题的容器日志
$ docker compose logs --tail=50 <服务名>
# 服务名：backend / worker / nginx / postgres / redis / flower

# 第三步：进容器内部调试
$ docker compose exec backend bash
```

---

### 问题 1：nginx 返回 502 Bad Gateway

**最可能原因**：容器被 `up -d` 重建后 IP 变了，nginx 还在用旧 IP。

```bash
$ docker compose restart nginx
```

如果还不行，检查 backend/frontend 是否在运行：

```bash
$ docker compose ps
$ docker compose logs backend --tail=20
```

---

### 问题 2：backend 容器反复重启（Exit 然后 Restarting）

**最可能原因**：数据库迁移失败，或者 .env 配置错误。

```bash
$ docker compose logs backend --tail=50
# 找到具体报错信息

# 常见：alembic 迁移失败，查看当前数据库版本
$ docker compose exec postgres psql -U urip -d urip -c "SELECT * FROM alembic_version;"
```

---

### 问题 3：Celery 任务不执行（检索卡住不动）

**最可能原因**：Redis 连接断了，或者 worker 挂了。

```bash
$ docker compose exec redis redis-cli ping
# 应该返回 PONG

$ docker compose logs worker --tail=50
$ docker compose restart worker beat
```

---

### 问题 4：服务器磁盘快满了

```bash
$ df -h   # 查看磁盘使用情况

# 清理 Docker 无用镜像和停止的容器（不会影响运行中的容器）
$ docker system prune -f

# 清理 60 天前的备份文件
$ find /opt/scholarpilot/backups -name "*.dump" -mtime +60 -delete
```

---

### 问题 5：HTTPS 证书过期，网站显示"不安全"

```bash
$ sudo certbot renew
$ docker compose restart nginx
```

---

### 问题 6：忘记生产环境数据库密码

```bash
$ cat /opt/scholarpilot/prod/.env | grep POSTGRES_PASSWORD
```

---

### 问题 7：想看 Flower 任务监控面板

Flower（:5555）没有对外开放，用 SSH 隧道访问：

```bash
# 本地电脑
> ssh -L 5555:localhost:5555 deploy@<服务器IP>
# 浏览器打开 http://localhost:5555
```

---

## 附录：快速命令速查

```bash
# ===== 日常运维 =====

# 查看所有服务状态
docker compose ps

# 实时查看日志（Ctrl+C 退出，服务继续跑）
docker compose logs -f backend
docker compose logs -f worker

# 重启某个服务
docker compose restart backend

# 停止所有服务（保留数据）
docker compose down

# 完整重建（改了 Dockerfile 或 requirements.txt 后）
docker compose down && docker compose build && docker compose up -d

# ===== 数据库 =====

# 立即备份（一行命令）
docker compose exec postgres pg_dump -U urip -Fc urip > /opt/scholarpilot/backups/$(date +%Y%m%d_%H%M%S).dump

# 进入数据库交互终端
docker compose exec postgres psql -U urip

# 查看所有表
docker compose exec postgres psql -U urip -c "\dt"

# ===== 更新生产版本 =====

# 只改了 Python 代码
git pull && docker compose restart backend worker beat

# 改了前端
git pull && docker compose build frontend && docker compose up -d frontend && docker compose restart nginx

# 改了数据库结构（先备份！）
/opt/scholarpilot/scripts/backup.sh && git pull && docker compose restart backend

# ===== 磁盘清理 =====

# 清理 Docker 无用资源
docker system prune -f

# 查看 Docker 磁盘占用详情
docker system df
```
