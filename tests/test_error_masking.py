"""P1-4：全局兜底异常处理脱敏 —— 不向前端回传内部细节，只给通用提示+trace id。"""
import json

import pytest

from main import _unhandled_zh


def _make_request(path: str = "/api/task/x"):
    from starlette.requests import Request
    scope = {
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "headers": [], "query_string": b"",
        "scheme": "http", "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_unhandled_error_masks_internal_details():
    """异常里若含 SQL/路径/表名等内部信息，绝不能原样回传前端。"""
    secret = "服务器内部错误：SELECT * FROM users WHERE password='x' /etc/passwd /opt/app/drama_agent/db/models.py"
    resp = await _unhandled_zh(_make_request(), ValueError(secret))
    body = json.loads(resp.body)
    assert resp.status_code == 500
    # 不包含内部细节
    assert "SELECT" not in body["detail"]
    assert "/etc/passwd" not in body["detail"]
    assert "models.py" not in body["detail"]
    # 只给通用提示 + trace id
    assert "服务器内部错误" in body["detail"]
    assert "错误码" in body["detail"]


@pytest.mark.asyncio
async def test_unhandled_error_returns_trace_id():
    """每次 500 返回一个 8 位十六进制错误码，方便按日志定位。"""
    resp = await _unhandled_zh(_make_request(), RuntimeError("boom"))
    body = json.loads(resp.body)
    code = body["detail"].split("错误码 ")[-1].rstrip("）")
    assert len(code) == 8
    assert all(c in "0123456789abcdef" for c in code)
