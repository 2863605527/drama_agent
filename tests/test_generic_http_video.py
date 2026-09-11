"""通用 HTTP 视频通道（硅基流动适配）单元测试：提交 payload 组装 + POST 轮询解析"""
import base64
import pytest

from tools import media_channel


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class TestSubmitPayload:
    def test_siliconflow_profile(self, monkeypatch, tmp_path):
        """硅基流动配置：model/image_size 注入、参考图转 base64 且字段名为 image、duration 被剔除"""
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResp({"requestId": "req-123"})

        monkeypatch.setattr(media_channel.requests, "post", fake_post)

        # 造一张本地参考图，模拟 /assets/uploads/xxx.png
        img = tmp_path / "ref.png"
        img.write_bytes(b"\x89PNG fake")
        profile = {
            "submit_url": "https://api.siliconflow.cn/v1/video/submit",
            "extra_fields": '{"model": "Wan-AI/Wan2.2-I2V-A14B", "image_size": "720x1280"}',
            "image_field": "image",
            "image_mode": "base64",
            "omit_fields": "duration",
            "task_id_path": "requestId",
        }
        ref = f"/assets/uploads/{img.name}"
        monkeypatch.setattr(media_channel, "_local_image_to_data_url", lambda u: "data:image/png;base64,QUJD")
        task_id = media_channel._video_http_submit("一句 prompt", ref, {"duration": 5}, 5, profile)

        assert task_id == "req-123"
        body = captured["json"]
        assert body["model"] == "Wan-AI/Wan2.2-I2V-A14B"
        assert body["image_size"] == "720x1280"
        assert body["image"] == "data:image/png;base64,QUJD"
        assert "duration" not in body          # 硅基不收 duration
        assert "image_url" not in body         # 字段名已改为 image
        assert body["prompt"] == "一句 prompt"

    def test_default_profile_keeps_duration_and_image_url(self, monkeypatch):
        """不配置时的默认行为保持向后兼容：duration + image_url"""
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["json"] = json
            return _FakeResp({"data": {"task_id": "t-1"}})

        monkeypatch.setattr(media_channel.requests, "post", fake_post)
        monkeypatch.setattr(media_channel, "VIDEO_HTTP_SUBMIT_URL", "https://api.example.com/v1/video/generate")
        task_id = media_channel._video_http_submit("p", "https://cdn.example.com/a.png", {"duration": 6}, 6, None)
        assert task_id == "t-1"
        assert captured["json"]["duration"] == 6
        assert captured["json"]["image_url"] == "https://cdn.example.com/a.png"


class TestPoll:
    def test_post_poll_with_body_template(self, monkeypatch):
        """硅基流动：POST 轮询 + {"requestId": "{task_id}"} 模板替换 + results.videos[0].url"""
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResp({
                "status": "Succeed",
                "results": {"videos": [{"url": "https://sf.example/v.mp4"}]},
            })

        monkeypatch.setattr(media_channel.requests, "post", fake_post)
        profile = {
            "poll_url": "https://api.siliconflow.cn/v1/video/status",
            "poll_method": "post",
            "poll_body": '{"requestId": "{task_id}"}',
            "status_path": "status",
            "success_status": "Succeed",
            "video_url_path": "results.videos[0].url",
        }
        r = media_channel._video_http_poll("req-abc", profile)
        assert captured["url"] == "https://api.siliconflow.cn/v1/video/status"
        assert captured["json"] == {"requestId": "req-abc"}
        assert r["status"] == "succeeded"
        assert r["video_url"] == "https://sf.example/v.mp4"

    def test_failed_reason_extracted(self, monkeypatch):
        """Failed 时错误信息优先取 reason 字段"""
        monkeypatch.setattr(
            media_channel.requests, "post",
            lambda url, json=None, headers=None, timeout=None: _FakeResp(
                {"status": "Failed", "reason": "内容审核未通过"}))
        profile = {
            "poll_url": "https://api.siliconflow.cn/v1/video/status",
            "poll_method": "post",
            "poll_body": '{"requestId": "{task_id}"}',
            "status_path": "status",
            "success_status": "Succeed",
        }
        r = media_channel._video_http_poll("req-x", profile)
        assert r["status"] == "failed"
        assert "内容审核未通过" in r["error"]

    def test_inprogress_is_pending(self, monkeypatch):
        monkeypatch.setattr(
            media_channel.requests, "post",
            lambda url, json=None, headers=None, timeout=None: _FakeResp({"status": "InProgress"}))
        profile = {
            "poll_url": "https://api.siliconflow.cn/v1/video/status",
            "poll_method": "post",
            "poll_body": '{"requestId": "{task_id}"}',
            "status_path": "status",
            "success_status": "Succeed",
        }
        assert media_channel._video_http_poll("req-y", profile)["status"] == "pending"


class TestLocalImageB64:
    def test_absolute_path(self, tmp_path):
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG")
        out = media_channel._local_image_to_data_url(str(img))
        assert out.startswith("data:image/png;base64,")
        assert base64.b64decode(out.split(",", 1)[1]) == b"\x89PNG"

    def test_external_url_passthrough_none(self):
        assert media_channel._local_image_to_data_url("https://cdn.example.com/x.png") is None
