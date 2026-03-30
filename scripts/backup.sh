#!/bin/bash
# ScholarPilot 数据库自动备份脚本
# 部署位置：/opt/scholarpilot/scripts/backup.sh
# cron 配置：0 3 * * * /opt/scholarpilot/scripts/backup.sh >> /var/log/scholarpilot-backup.log 2>&1

set -e

BACKUP_DIR="/opt/scholarpilot/backups"
COMPOSE_DIR="/opt/scholarpilot/prod"
KEEP_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/auto_$DATE.dump"

echo "[$(date)] 开始备份数据库..."

# 确保备份目录存在
mkdir -p "$BACKUP_DIR"

# 执行 pg_dump（-Fc 自定义格式，比 SQL 小，支持并行恢复）
docker compose -f "$COMPOSE_DIR/docker-compose.yml" exec -T postgres \
    pg_dump -U urip -Fc urip > "$BACKUP_FILE"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "[$(date)] 备份完成：$BACKUP_FILE ($SIZE)"

# 删除超过 KEEP_DAYS 天的旧备份
DELETED=$(find "$BACKUP_DIR" -name "auto_*.dump" -mtime +$KEEP_DAYS -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date)] 已清理 $DELETED 个超过 ${KEEP_DAYS} 天的旧备份"
fi

echo "[$(date)] 备份任务完成"
