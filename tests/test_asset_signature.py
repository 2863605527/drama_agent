"""P0：/assets 媒体访问签名测试（防未授权遍历/盗链）"""
import time

import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth.asset_sign import (
    sign_asset_path, verify_asset_signature, sign_nested_assets, raw_nested_assets,
)
from main import SignedAssets


@pytest.fixture
def client():
    return None


async def _serve(static, path, query_string: bytes):
    """调用 SignedAssets.get_response（path 为挂载内相对路径）并经 ASGI send 收集响应。"""
    scope = {
        "type": "http", "method": "GET", "path": f"/assets/{path}",
        "query_string": query_string, "headers": [], "scheme": "http",
        "server": ("test", 80), "client": ("test", 1), "root_path": "",
        "http_version": "1.1", "app": None,
    }
    chunks = []
    start = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            start["status"] = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message["body"])

    try:
        resp = await static.get_response(path, scope)
        await resp(scope, receive, send)
        return start.get("status", 500), b"".join(chunks)
    except StarletteHTTPException as e:
        return e.status_code, None


def test_sign_and_verify_roundtrip():
    url = sign_asset_path("/assets/images/x.png")
    assert url.startswith("/assets/images/x.png?exp=")
    path, query = url.split("?", 1)
    params = dict(kv.split("=") for kv in query.split("&"))
    assert verify_asset_signature(path, params["exp"], params["sig"]) is True
    # 篡改签名 → 失败
    assert verify_asset_signature(path, params["exp"], "deadbeef") is False
    # 过期 → 失败
    assert verify_asset_signature(path, str(int(time.time()) - 10), params["sig"]) is False
    # 非数字 exp → 失败
    assert verify_asset_signature(path, "abc", params["sig"]) is False


def test_sign_asset_path_idempotent():
    # 已带签名的 URL 不再二次签名
    once = sign_asset_path("/assets/videos/a.mp4")
    twice = sign_asset_path(once)
    assert once == twice


def test_nested_sign_and_raw():
    data = {
        "characters": [{"reference_image": "/assets/images/c.png"}],
        "scenes": [{"day_image_url": "/assets/images/d.png"}],
        "segments": [{"video_url": "/assets/videos/s.mp4"}],
        "keep": "http://example.com/x.png",
        "none": None,
    }
    signed = sign_nested_assets(data)
    assert "?exp=" in signed["characters"][0]["reference_image"]
    assert "?exp=" in signed["scenes"][0]["day_image_url"]
    assert "?exp=" in signed["segments"][0]["video_url"]
    assert signed["keep"] == "http://example.com/x.png"
    assert signed["none"] is None
    # 回退 raw 恢复存储相对路径
    raw = raw_nested_assets(signed)
    assert raw["characters"][0]["reference_image"] == "/assets/images/c.png"
    assert raw["segments"][0]["video_url"] == "/assets/videos/s.mp4"


def test_assets_route_requires_signature(tmp_path):
    """无签名访问 /assets 下真实文件 → 403；带签名 → 200。"""
    target = tmp_path / "probe.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    static = SignedAssets(directory=str(tmp_path))

    import asyncio

    async def run():
        # 无签名 → 403
        code, _ = await _serve(static, "probe.png", b"")
        assert code == 403
        # 签名错误 → 403
        code, _ = await _serve(static, "probe.png", b"exp=9999999999&sig=bad")
        assert code == 403
        # 正确签名 → 200 且内容为 PNG
        signed = sign_asset_path("/assets/probe.png")
        _, qs = signed.split("?", 1)
        code, body = await _serve(static, "probe.png", qs.encode())
        assert code == 200
        assert body.startswith(b"\x89PNG")
    asyncio.run(run())
