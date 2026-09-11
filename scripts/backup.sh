#!/usr/bin/env bash
# ============================================================================
# Drama-Agent 全量备份脚本（Linux 服务器 / Docker 环境）
#
# 备份内容：
#   1. MySQL drama_agent 库 -> backups/mysql/drama_YYYYmmdd_HHMMSS.sql.gz
#   2. assets 素材目录       -> backups/assets/assets_YYYYmmdd_HHMMSS.tar.gz
#
# 用法：
#   bash scripts/backup.sh                 # 默认保留最近 7 天
#   DAYS_TO_KEEP=14 bash scripts/backup.sh
#   DRAMA_MYSQL_PWD=xxx bash scripts/backup.sh   # 密码走环境变量（推荐，不写死）
#
# 定时执行（crontab -e，每天 03:00）：
#   0 3 * * * cd /opt/drama_agent && bash scripts/backup.sh >> logs/backup.log 2>&1
#
# 恢复：
#   gunzip -c backups/mysql/drama_*.sql.gz | docker exec -i drama-mysql mysql -udrama -p drama_agent
#   tar -xzf backups/assets/assets_*.tar.gz -C /opt/drama_agent/
# ============================================================================
set -euo pipefail

# 项目根 = 本脚本上级目录
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
DAYS_TO_KEEP="${DAYS_TO_KEEP:-7}"
# 数据库密码：优先环境变量，否则用 docker-compose 默认值
MYSQL_PWD="${DRAMA_MYSQL_PWD:-drama_2024}"
MYSQL_CONTAINER="drama-mysql"
MYSQL_DB="drama_agent"
MYSQL_USER="drama"

SQL_DIR="$ROOT/backups/mysql"
AS_DIR="$ROOT/backups/assets"
mkdir -p "$SQL_DIR" "$AS_DIR"

# ---------- 1. MySQL dump（容器内 gzip 落 /tmp，再 docker cp 出来，避免管道编码问题）----------
echo "[1/3] 备份 MySQL ..."
SQL_FILE="$SQL_DIR/drama_$STAMP.sql.gz"
TMP_IN_CONTAINER="/tmp/drama_backup_$STAMP.sql.gz"
docker exec -e MYSQL_PWD="$MYSQL_PWD" "$MYSQL_CONTAINER" sh -c \
  "mysqldump -u$MYSQL_USER --single-transaction --no-tablespaces --routines --triggers $MYSQL_DB | gzip > $TMP_IN_CONTAINER"
docker cp "$MYSQL_CONTAINER:$TMP_IN_CONTAINER" "$SQL_FILE"
docker exec "$MYSQL_CONTAINER" rm -f "$TMP_IN_CONTAINER"
if [ ! -s "$SQL_FILE" ]; then
  echo "MySQL 备份失败：$SQL_FILE 为空或未生成" >&2
  exit 1
fi
echo "    完成：$SQL_FILE ($(du -h "$SQL_FILE" | cut -f1))"

# ---------- 2. assets 目录打包 ----------
echo "[2/3] 备份 assets 素材目录 ..."
TAR_FILE="$AS_DIR/assets_$STAMP.tar.gz"
if [ -d "$ROOT/assets" ]; then
  tar -C "$ROOT" -czf "$TAR_FILE" assets
  if [ ! -s "$TAR_FILE" ]; then
    echo "assets 备份失败：$TAR_FILE 为空或未生成" >&2
    exit 1
  fi
  echo "    完成：$TAR_FILE ($(du -h "$TAR_FILE" | cut -f1))"
else
  echo "    跳过：assets 目录不存在"
fi

# ---------- 3. 清理过期备份 ----------
echo "[3/3] 清理 $DAYS_TO_KEEP 天前的旧备份 ..."
find "$SQL_DIR" -name "*.sql.gz" -type f -mtime +"$DAYS_TO_KEEP" -delete
find "$AS_DIR"  -name "*.tar.gz" -type f -mtime +"$DAYS_TO_KEEP" -delete

echo "备份完成 - 保留最近 $DAYS_TO_KEEP 天"
