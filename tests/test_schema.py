"""Pydantic schema 校验单元测试"""
import pytest
from pydantic import ValidationError
from schema.drama_schema import SubmitDramaRequest
from auth.schemas import RegisterRequest, LoginRequest


class TestAuthSchema:
    def test_register_valid(self):
        r = RegisterRequest(username="tom", password="123456")
        assert r.username == "tom"

    def test_username_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="ab", password="123456")  # 最少 3 位

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="tom", password="123")  # 最少 6 位


class TestSubmitSchema:
    def test_default_style(self):
        r = SubmitDramaRequest(user_prompt="一个故事")
        assert r.style == "anime"

    def test_empty_prompt_rejected(self):
        with pytest.raises(ValidationError):
            SubmitDramaRequest(user_prompt="")

class TestChannelSegmentSanitize:
    def test_empty_custom_segment_deactivated(self):
        from schema import channel_schema as chs
        # 图片填全、视频段残留 generic_http 空壳 -> 视频自动降级 env，不卡保存
        cfg = {
            "image": {"channel": "generic_http", "base_url": "https://x", "token": "t", "model": "m"},
            "video": {"channel": "generic_http"},
        }
        out = chs.deactivate_empty_segments(cfg)
        assert out["image"]["channel"] == "generic_http"
        assert out["video"]["channel"] == chs.CH_ENV

    def test_partial_filled_segment_kept(self):
        from schema import channel_schema as chs
        # 只填了地址、缺 token/model -> 保留，交给 validate 如实报错
        cfg = {"image": {"channel": "generic_http", "base_url": "https://x"}}
        out = chs.deactivate_empty_segments(cfg)
        assert out["image"]["channel"] == "generic_http"
        assert chs.validate_profile("image", out["image"])  # 非空=确有缺失提示
