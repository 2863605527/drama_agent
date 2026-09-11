# -*- coding: utf-8 -*-
"""注册账号 / 密码的格式校验（前后端规则保持一致）。

规则（按需求收紧，禁止中文与特殊字符，避免脏账号与不可输入密码）：
  - 用户名：3~20 位，只能由英文字母、数字、下划线组成，必须以字母开头；
  - 密码：6~20 位，只能由英文字母和数字组成（不允许中文、空格及任何特殊符号）。
"""
import re

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,19}$")
PASSWORD_RE = re.compile(r"^[A-Za-z0-9]{6,20}$")

USERNAME_HINT = "账号需 3~20 位，以字母开头，只能包含字母、数字、下划线，不允许中文或特殊字符"
PASSWORD_HINT = "密码需 6~20 位，只能包含英文字母和数字，不允许中文、空格或特殊字符"


def validate_username(username: str) -> str | None:
    """合法返回 None；不合法返回中文错误说明。"""
    if not username or not USERNAME_RE.match(username.strip()):
        return USERNAME_HINT
    return None


def validate_password(password: str) -> str | None:
    if not password or not PASSWORD_RE.match(password):
        return PASSWORD_HINT
    return None
