# -*- coding: utf-8 -*-
"""通用 HTTP 通道：平台预设自动识别 + 只填 base_url/token/model 端到端请求体校验。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.http_presets import normalize_http_media, detect_platform
import tools.media_channel as mc


# ----------------------- 归一化预设 -----------------------

def test_siliconflow_image_minimal():
    p = normalize_http_media(
        {"channel": "generic_http", "base_url": "https://api.siliconflow.cn",
         "token": "sk", "model": "Kwai-Kolors/Kolors"}, "image")
    assert p["endpoint"] == "https://api.siliconflow.cn/v1/images/generations"
    assert p["result_path"] == "images[0].url"
    assert p["size_field"] == "image_size"
    assert p["image_field"] == "image"


def test_siliconflow_video_minimal_full_poll():
    p = normalize_http_media(
        {"channel": "generic_http", "base_url": "https://api.siliconflow.cn/v1",
         "token": "sk", "model": "Wan-AI/Wan2.2-I2V-A14B"}, "video")
    # base_url 填到 /v1 也只取 host，不会重复拼 /v1
    assert p["submit_url"] == "https://api.siliconflow.cn/v1/video/submit"
    assert p["poll_url"] == "https://api.siliconflow.cn/v1/video/status"
    assert p["poll_method"] == "post"
    assert "{task_id}" in p["poll_body"]
    assert p["task_id_path"] == "requestId"
    assert p["success_status"] == "Succeed"
    assert p["video_url_path"] == "results.videos[0].url"
    assert "duration" in p["omit_fields"]


def test_unknown_platform_openai_fallback():
    p = normalize_http_media(
        {"channel": "generic_http", "base_url": "https://api.whatever.io"}, "image")
    assert p["endpoint"].endswith("/v1/images/generations")
    assert p["result_path"] == "data[0].url"
    assert detect_platform("https://api.whatever.io")["id"] == "openai_compatible"


def test_zhipu_video():
    p = normalize_http_media(
        {"channel": "generic_http", "base_url": "https://open.bigmodel.cn"}, "video")
    assert p["poll_method"] == "get"
    assert p["status_path"] == "task_status"
    assert p["success_status"] == "SUCCESS"
    assert "{task_id}" in p["poll_url"]


def test_user_advanced_value_wins_and_idempotent():
    base = {"channel": "generic_http", "base_url": "https://api.siliconflow.cn",
            "success_status": "DONE", "video_url_path": "a.b[0]"}
    p1 = normalize_http_media(base, "video")
    assert p1["success_status"] == "DONE"          # 用户值不覆盖
    assert p1["video_url_path"] == "a.b[0]"
    assert p1["task_id_path"] == "requestId"       # 其余仍自动补
    p2 = normalize_http_media(p1, "video")         # 幂等
    assert p1 == p2


def test_siliconflow_poll_query_normalized():
    # 用户把 requestId 误填进 POST 轮询 URL 的 query，应规范化为干净 URL（id 走 body）
    p = normalize_http_media({
        "channel": "generic_http",
        "submit_url": "https://api.siliconflow.cn/v1/video/submit",
        "poll_url": "https://api.siliconflow.cn/v1/video/status?requestId={task_id}",
        "poll_method": "post"}, "video")
    assert p["poll_url"] == "https://api.siliconflow.cn/v1/video/status"
    assert "?" not in p["poll_url"]
    assert p["poll_body"] == '{"requestId": "{task_id}"}'


def test_non_generic_untouched_and_empty():
    assert normalize_http_media({"channel": "volc_cv"}, "image") == {"channel": "volc_cv"}
    assert normalize_http_media(None, "image") is None
    # 无 base_url 不臆造
    p = normalize_http_media({"channel": "generic_http"}, "video")
    assert not p.get("submit_url")


# ----------------------- 端到端请求体（mock requests.post） -----------------------

class _FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, ""
    def json(self):
        return self._p


def test_siliconflow_image_request_body(monkeypatch):
    captured = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, payload=json, headers=headers)
        return _FakeResp({"images": [{"url": "http://cdn/1.png"}]})
    monkeypatch.setattr(mc.requests, "post", fake_post)
    url = mc._image_http(
        "夜晚酒馆", 1024, 1024,
        profile={"channel": "generic_http", "base_url": "https://api.siliconflow.cn",
                 "token": "sk-x", "model": "Kwai-Kolors/Kolors"})
    assert url == "http://cdn/1.png"
    assert captured["url"] == "https://api.siliconflow.cn/v1/images/generations"
    assert captured["payload"]["model"] == "Kwai-Kolors/Kolors"
    assert captured["payload"]["image_size"] == "1024x1024"   # 硅基单一尺寸字段
    assert "width" not in captured["payload"]                 # 不发 width/height
    assert captured["headers"]["Authorization"] == "Bearer sk-x"


def test_siliconflow_video_submit_and_poll(monkeypatch):
    calls = []
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        if url.endswith("/video/submit"):
            return _FakeResp({"requestId": "job-123"})
        return _FakeResp({"status": "Succeed", "results": {"videos": [{"url": "http://cdn/v.mp4"}]}})
    monkeypatch.setattr(mc.requests, "post", fake_post)
    prof = {"channel": "generic_http", "base_url": "https://api.siliconflow.cn",
            "token": "sk", "model": "Wan-AI/Wan2.2-I2V-A14B"}
    tid = mc._video_http_submit("镜头", "", {"duration": 5}, 5, prof)
    assert tid == "job-123"
    submit_url, submit_body = calls[0]
    assert submit_url.endswith("/video/submit")
    assert submit_body["model"] == "Wan-AI/Wan2.2-I2V-A14B"
    assert "duration" not in submit_body           # 硅基不收 duration，已剔除
    res = mc._video_http_poll("job-123", prof)
    poll_url, poll_body = calls[1]
    assert poll_url.endswith("/video/status")
    assert poll_body == {"requestId": "job-123"}   # POST 轮询体自动补
    assert res["status"] == "succeeded"
    assert res["video_url"] == "http://cdn/v.mp4"


def test_siliconflow_video_poll_failed(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp({"status": "Failed", "reason": "content blocked"})
    monkeypatch.setattr(mc.requests, "post", fake_post)
    prof = {"channel": "generic_http", "base_url": "https://api.siliconflow.cn"}
    res = mc._video_http_poll("j", prof)
    assert res["status"] == "failed"
    assert "blocked" in res["error"]
