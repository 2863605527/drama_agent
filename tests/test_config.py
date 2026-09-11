"""配置管理单元测试"""
from core.config import Settings


class TestSettings:
    def test_database_url_build(self):
        s = Settings(mysql_host="h", mysql_port=3307, mysql_user="u",
                     mysql_password="p", mysql_database="d")
        assert s.database_url == "mysql+aiomysql://u:p@h:3307/d?charset=utf8mb4"

    def test_cors_wildcard(self):
        s = Settings(cors_origins="*")
        assert s.cors_origin_list == ["*"]

    def test_cors_list(self):
        s = Settings(cors_origins="http://a.com, http://b.com")
        assert s.cors_origin_list == ["http://a.com", "http://b.com"]

    def test_validate_required_detects_missing_key(self):
        s = Settings(llm_api_key="", volc_access_key="", volc_secret_key="")
        problems = s.validate_required()
        joined = " ".join(problems)
        assert "LLM_API_KEY" in joined
        assert "VOLC" in joined

    def test_production_requires_jwt_secret(self):
        s = Settings(environment="production",
                     jwt_secret_key="please-change-this-to-a-random-secret-string",
                     llm_api_key="x", volc_access_key="x", volc_secret_key="x")
        problems = s.validate_required()
        assert any("JWT_SECRET_KEY" in p for p in problems)

    def test_development_no_jwt_error(self):
        s = Settings(environment="development",
                     jwt_secret_key="please-change-this-to-a-random-secret-string",
                     llm_api_key="x", volc_access_key="x", volc_secret_key="x")
        problems = s.validate_required()
        assert not any("JWT_SECRET_KEY" in p for p in problems)
