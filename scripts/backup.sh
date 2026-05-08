#!/bin/bash
# ScholarPilot 数据库自动备份脚本
#
# 用法：
#   COMPOSE_DIR=/path/to/scholarpilot BACKUP_DIR=/path/to/backups ./backup.sh
#
# cron 示例：
#   0 3 * * * COMPOSE_DIR=/path/to/scholarpilot BACKUP_DIR=/path/to/backups /path/to/scripts/backup.sh >> /var/log/scholarpilot-backup.log 2>&1

set -e

BACKUP_DIR="${BACKUP_DIR:-./backups}"
COMPOSE_DIR="${COMPOSE_DIR:-.}"
KEEP_DAYS="${KEEP_DAYS:-30}"
PG_USER="${POSTGRES_USER:-urip}"
PG_DB="${POSTGRES_DB:-urip}"

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/auto_$DATE.dump"

echo "[$(date)] 开始备份数据库..."

mkdir -p "$BACKUP_DIR"

docker compose -f "$COMPOSE_DIR/docker-compose.yml" exec -T postgres \
    pg_dump -U "$PG_USER" -Fc "$PG_DB" > "$BACKUP_FILE"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "[$(date)] 备份完成：$BACKUP_FILE ($SIZE)"

DELETED=$(find "$BACKUP_DIR" -name "auto_*.dump" -mtime +$KEEP_DAYS -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date)] 已清理 $DELETED 个超过 ${KEEP_DAYS} 天的旧备份"
fi

echo "[$(date)] 备份任务完成"
