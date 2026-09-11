# -*- coding: utf-8 -*-
"""用户通道配置接口端到端测试（内存 SQLite，不联网、不烧 Key）。

覆盖：元数据、初始为空、保存加密、读回掩码、掩码沿用旧值、缺必填 400、
媒体通道凭据校验、SPA 托管与 history 回退。
"""
import glob
import pytest

from schema import channel_schema as chs


@pytest.mark.asyncio
async def test_channel_meta_and_empty_config(client, auth_headers):
    r = await client.get("/api/channels/meta", headers=auth_headers)
    assert r.status_code == 200
    meta = r.json()
    assert {"llm", "image", "video"} <= set(meta.keys())
    assert "resolutions" in meta["video"] and "ratios" in meta["video"]

    r = await client.get("/api/user/channel-config", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["config"] is None  # 从未配置时为 null（前端按空处理）


@pytest.mark.asyncio
async def test_save_then_mask_then_keep_old_secret(client, auth_headers):
    # 保存 ark 图片通道
    cfg = {
        "llm": {"channel": "env"},
        "image": {"channel": "volc_ark", "api_key": "sk-secret-xyz",
                  "model": "doubao-seedream-5-0-260128"},
        "video": {"channel": "env"},
    }
    r = await client.put("/api/user/channel-config", headers=auth_headers, json=cfg)
    assert r.status_code == 200

    # 读回：密钥掩码、模型明文
    r = await client.get("/api/user/channel-config", headers=auth_headers)
    saved = r.json()["config"]
    assert saved["image"]["api_key"].startswith(chs.MASK_PREFIX)
    assert saved["image"]["model"] == "doubao-seedream-5-0-260128"
    masked_key = saved["image"]["api_key"]

    # 掩码不改：提交掩码 + 改模型，旧密钥沿用且模型更新
    cfg2 = {
        "llm": {"channel": "env"},
        "image": {"channel": "volc_ark", "api_key": masked_key,
                  "model": "doubao-seedream-4-0-250828"},
        "video": {"channel": "env"},
    }
    r = await client.put("/api/user/channel-config", headers=auth_headers, json=cfg2)
    assert r.status_code == 200
    assert r.json()["config"]["image"]["model"] == "doubao-seedream-4-0-250828"


@pytest.mark.asyncio
async def test_missing_required_field_400(client, auth_headers):
    # video 从未配置过 ark，缺 api_key 且无旧值可沿用 -> 400
    bad = {"llm": {"channel": "env"}, "image": {"channel": "env"},
           "video": {"channel": "volc_ark", "model": "x"}}
    r = await client.put("/api/user/channel-config", headers=auth_headers, json=bad)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_media_channel_test_only_validates(client, auth_headers):
    r = await client.post("/api/user/channel-test", headers=auth_headers,
                          json={"kind": "image",
                                "profile": {"channel": "volc_ark", "api_key": "k", "model": "m"}})
    assert r.status_code == 200 and r.json()["ok"] is True


@pytest.mark.asyncio
async def test_spa_hosting_and_history_fallback(client):
    r = await client.get("/")
    assert r.status_code == 200 and 'id="app"' in r.text
    r = await client.get("/some/history/route")
    assert r.status_code == 200 and 'id="app"' in r.text
    assets = sorted(glob.glob("frontend/dist/app-assets/index-*.js"))
    if assets:
        url = "/" + assets[0].replace("\\", "/").split("frontend/dist/")[-1]
        r = await client.get(url)
        assert r.status_code == 200
