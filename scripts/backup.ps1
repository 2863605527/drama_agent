# ============================================================================
# Drama-Agent 全量备份脚本（Windows / PowerShell + Docker 环境）
#
# 备份内容：
#   1. MySQL drama_agent 库   -> backups/mysql/drama_YYYYmmdd_HHMMSS.sql.gz
#   2. assets 素材目录（图片/视频/音频） -> backups/assets/assets_YYYYmmdd_HHMMSS.tar.gz
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\backup.ps1            # 默认保留最近 7 天
#   powershell -ExecutionPolicy Bypass -File scripts\backup.ps1 -DaysToKeep 14
#   $env:DRAMA_MYSQL_PWD="你的库密码"; powershell ...\backup.ps1          # 密码不写死在脚本里（可选）
#
# 定时执行（示例，每天 03:00）：
#   schtasks /Create /TN "DramaAgentBackup" /SC DAILY /ST 03:00 /TR "powershell -ExecutionPolicy Bypass -File F:\AI学习\drama_agent\scripts\backup.ps1" /F
#
# 恢复：
#   MySQL： gunzip -c drama_*.sql.gz | docker exec -i drama-mysql mysql -udrama -pdrama_2024 drama_agent
#   assets： tar -xzf assets_*.tar.gz -C F:\AI学习\drama_agent\（覆盖 assets 目录）
# ============================================================================
param(
    [int]$DaysToKeep = 7
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root   = Split-Path -Parent $PSScriptRoot          # 项目根
$Stamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$SqlDir = Join-Path $Root "backups\mysql"
$AsDir  = Join-Path $Root "backups\assets"

# 数据库密码：优先取环境变量 DRAMA_MYSQL_PWD，未设置时用 docker-compose 默认值
# （与 docker-compose.yml 的 MYSQL_PASSWORD 保持一致；本脚本仅本机运维使用）
$MYSQL_PWD = if ($env:DRAMA_MYSQL_PWD) { $env:DRAMA_MYSQL_PWD } else { "drama_2024" }

New-Item -ItemType Directory -Force -Path $SqlDir, $AsDir | Out-Null

# ---------- 1. MySQL dump ----------
Write-Host "[1/3] 备份 MySQL ..."
# mysqldump+gzip 在容器内完成并落盘到 /tmp，再 docker cp 出来；
# 避免 PowerShell 管道对二进制流做文本解码导致 gzip 损坏。
$sqlFile = Join-Path $SqlDir "drama_$Stamp.sql.gz"
$tmpInContainer = "/tmp/drama_backup_$Stamp.sql.gz"
docker exec -e MYSQL_PWD=$MYSQL_PWD drama-mysql sh -c "mysqldump -udrama --single-transaction --no-tablespaces --routines --triggers drama_agent | gzip > $tmpInContainer"
if ($LASTEXITCODE -ne 0) { throw "mysqldump 在容器内执行失败（exit=$LASTEXITCODE），请确认 drama-mysql 容器运行中" }
docker cp ("drama-mysql:" + $tmpInContainer) $sqlFile
if ($LASTEXITCODE -ne 0) { throw "docker cp 拉取备份失败（exit=$LASTEXITCODE）" }
docker exec drama-mysql rm -f $tmpInContainer
if (-not (Test-Path $sqlFile) -or (Get-Item $sqlFile).Length -eq 0) {
    throw "MySQL 备份失败：$sqlFile 为空或未生成"
}
$mb = [math]::Round((Get-Item $sqlFile).Length / 1MB, 2)
Write-Host "    完成：$sqlFile ($mb MB)"

# ---------- 2. assets 目录打包 ----------
Write-Host "[2/3] 备份 assets 素材目录 ..."
$tarFile = Join-Path $AsDir "assets_$Stamp.tar.gz"
if (Test-Path (Join-Path $Root "assets")) {
    tar -C $Root -czf $tarFile assets
    if ($LASTEXITCODE -ne 0) { throw "assets 打包失败（exit=$LASTEXITCODE）" }
    if (-not (Test-Path $tarFile) -or (Get-Item $tarFile).Length -eq 0) {
        throw "assets 备份失败：$tarFile 为空或未生成"
    }
    $mb2 = [math]::Round((Get-Item $tarFile).Length / 1MB, 2)
    Write-Host "    完成：$tarFile ($mb2 MB)"
} else {
    Write-Host "    跳过：assets 目录不存在"
}

# ---------- 3. 清理过期备份 ----------
Write-Host "[3/3] 清理 $DaysToKeep 天前的旧备份 ..."
$cutoff = (Get-Date).AddDays(-$DaysToKeep)
Get-ChildItem $SqlDir -Filter "*.sql.gz" | Where-Object { $_.LastWriteTime -lt $cutoff } | Remove-Item -Force
Get-ChildItem $AsDir  -Filter "*.tar.gz" | Where-Object { $_.LastWriteTime -lt $cutoff } | Remove-Item -Force

Write-Host "备份完成 - 保留最近 $DaysToKeep 天"
