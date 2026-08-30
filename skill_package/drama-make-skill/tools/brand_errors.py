"""火山 / 通用 API 业务错误码 → 友好中文（共用工具）
video_tool / image_tool 都会用，避免重复。"""
import re
import json


# 已知业务错误码映射（中文友好提示）
_BRAND_ERROR_MSGS = {
    # 并发 / 配额
    50430: "视频/图片服务并发数已达上限，已自动重试多次仍受限，请稍后再试（约 30 秒~1 分钟）；可在 .env 调小 VIDEO_MAX_CONCURRENCY / IMAGE_MAX_CONCURRENCY",
    # 权限 / 配额
    50400: "服务未开通或权限不足：请到火山引擎控制台开通「即梦AI」服务（https://console.volcengine.com/ai/overview），或检查 AK/SK 是否正确",
    # 内容安全审核（用户最常遇到的就是这两个）
    50412: "内容安全审核未通过：prompt 或参考图含违规内容（涉政/涉暴/色情/敏感词等），请修改 prompt（去掉敏感词、调整角色/场景描述）后重试。可联系火山侧开通白名单或换 prompt 重新生成",
    50413: "内容安全审核未通过：参考图含违规内容，请更换参考图或上传本地图片",
    # 参数错误
    50500: "服务内部错误，请稍后重试",
    50501: "参数错误：可能 prompt 含违规内容或超出长度，请简化后重试",
    50502: "参数错误：参考图 URL 无效或不可访问，请重新生成或上传本地图片",
    50503: "服务繁忙，请稍后重试",
    50504: "生成超时，请重试或减少视频时长",
    50505: "参数错误：prompt 格式不符（可能包含即梦无法解析的 XML 标签如 <node-asset>），请使用纯中文/英文自然语言描述，或切到 volc_ark 通道",
    # HTTP
    400: "请求参数错误：请检查 .env 中的模型/时长配置",
    401: "未授权：API Key 错误或过期，请检查 .env",
    403: "无权限：账号未开通该服务",
}

_GENERIC_BRAND_ERROR = "服务调用失败，请稍后重试"
_KIND_VIDEO = "视频"
_KIND_IMAGE = "图片"


def _extract_code_and_msg(s):
    """从可能含嵌套花括号的字符串中提取 code 数字 + message 文本。"""
    cm = re.search(r'"code"\s*:\s*(\d+)', s)
    if not cm:
        return None, ""
    code = int(cm.group(1))
    # message 可能含转义引号，用非贪婪匹配直到下一个 " 或 "},"
    mm = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
    raw_msg = mm.group(1) if mm else ""
    # 还原常见转义
    try:
        raw_msg = raw_msg.encode("utf-8").decode("unicode_escape", errors="replace")
    except Exception:
        raw_msg = raw_msg.replace("\\\"", "\"").replace("\\\\", "\\").replace("\\n", " ")
    return code, raw_msg


def translate_brand_error(resp, kind: str = "视频"):
    """把火山 API 业务错误翻译成友好中文。
    支持 dict / str / bytes / Exception / 任意输入。kind: '视频' | '图片'"""
    if resp is None:
        return _GENERIC_BRAND_ERROR
    if isinstance(resp, Exception):
        resp = str(resp)
    if isinstance(resp, bytes):
        try:
            resp = resp.decode("utf-8", errors="replace")
        except Exception:
            return _GENERIC_BRAND_ERROR
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except Exception:
            code, raw_msg = _extract_code_and_msg(resp)
            if code is not None:
                if code in _BRAND_ERROR_MSGS:
                    return _BRAND_ERROR_MSGS[code] + f"（code={code}）"
                if raw_msg:
                    return f"{kind}服务返回错误：{raw_msg[:120]}（code={code}）"
                return f"{kind}服务返回错误码 {code}"
            return resp[:200] if len(resp) > 200 else resp
    if not isinstance(resp, dict):
        s = str(resp)
        return s[:200] if len(s) > 200 else s
    code = resp.get("code")
    raw_msg = resp.get("message", "")
    request_id = resp.get("request_id", "")
    if code in _BRAND_ERROR_MSGS:
        zh = _BRAND_ERROR_MSGS[code]
        suffix = f"（服务商 code={code}）" + (f" req_id={request_id}" if request_id else "")
        return f"{zh}{suffix}"
    if raw_msg:
        return f"{kind}服务返回错误：{raw_msg[:120]}（code={code}）"
    return f"{kind}服务返回错误码 {code}"
