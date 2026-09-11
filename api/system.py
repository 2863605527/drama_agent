"""系统运维接口：健康检查 + Prometheus 指标"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from core import metrics
from db.database import AsyncSessionLocal

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    """健康检查：探测应用与 MySQL 连通性，供 Docker / 负载均衡使用"""
    db_status = "ok"
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)[:80]}"
    overall = "ok" if db_status == "ok" else "degraded"
    return JSONResponse(
        status_code=200 if db_status == "ok" else 503,
        content={"status": overall, "database": db_status},
    )


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标抓取端点（需安装 prometheus-client 才有真实数据）"""
    payload, content_type = metrics.metrics_payload()
    return Response(content=payload, media_type=content_type)
