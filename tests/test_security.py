"""密码哈希与 JWT 单元测试"""
from core.security import hash_password, verify_password
from auth.jwt import create_access_token, decode_access_token


class TestPassword:
    def test_hash_and_verify_ok(self):
        h = hash_password("my-password-123")
        assert h != "my-password-123"
        assert verify_password("my-password-123", h)

    def test_wrong_password(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_long_password_no_bcrypt_limit(self):
        """pbkdf2 无 bcrypt 72 字节限制"""
        long_pw = "a" * 200
        h = hash_password(long_pw)
        assert verify_password(long_pw, h)

    def test_each_hash_unique(self):
        """同一密码两次哈希结果不同（加盐）"""
        assert hash_password("same") != hash_password("same")


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token(42, "bob")
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["username"] == "bob"

    def test_invalid_token(self):
        assert decode_access_token("not-a-jwt") is None

    def test_tampered_token(self):
        token = create_access_token(1, "a")
        assert decode_access_token(token + "x") is None
