"""
translator.py - LLM 翻译接口
使用 requests 调用 OpenAI 兼容 API，集成翻译缓存
"""

import logging
import requests
from config import LLM_API_KEY, LLM_API_URL, LLM_MODEL, LLM_TIMEOUT
from prompt_builder import build_prompt
from translation_cache import get_cached_translation, set_cached_translation

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 3
_consecutive_errors = 0

def reset_errors():
    """Reset the consecutive error counter before an OCR pass"""
    global _consecutive_errors
    _consecutive_errors = 0


def translate_text(text: str) -> str:
    """
    翻译英文文本为中文。
    优先查询缓存，未命中则调用 LLM API。

    :param text: 英文原文
    :return: 中文译文（失败时返回原文）
    """
    text = text.strip()
    if not text:
        return ""

    global _consecutive_errors
    if _consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
        logger.warning("翻译 API 连续出错次数过多，跳过本次请求")
        return text

    # 查询缓存
    cached = get_cached_translation(text)
    if cached is not None:
        logger.debug(f"缓存命中: {text!r} → {cached!r}")
        return cached

    # 调用 LLM
    translation = _call_llm(text)
    if translation:
        set_cached_translation(text, translation)

    return translation or text


def _call_llm(text: str) -> str:
    """
    调用 LLM API 执行翻译。

    :param text: 原文
    :return: 译文，失败返回空字符串
    """
    global _consecutive_errors
    if not LLM_API_KEY:
        logger.warning("LLM_API_KEY 未配置，无法翻译")
        return ""

    system_prompt, user_message = build_prompt(text)

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
    }

    try:
        url_to_call = LLM_API_URL.strip()
        # 兜底自动修正，防止用户配了基础地址但没写路径
        if "api.deepseek.com" in url_to_call and not url_to_call.endswith("/completions"):
            url_to_call = "https://api.deepseek.com/chat/completions"
            
        resp = requests.post(
            url_to_call,
            headers=headers,
            json=payload,
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        translation = data["choices"][0]["message"]["content"].strip()
        logger.info(f"LLM 翻译成功: {text!r} → {translation!r} (URL: {url_to_call})")
        _consecutive_errors = 0  # 成功则重置错误计数
        return translation
    except requests.exceptions.Timeout:
        logger.error(f"LLM API 请求超时 (URL: {LLM_API_URL})")
        _consecutive_errors += 1
    except requests.exceptions.RequestException as e:
        status_code = getattr(e.response, "status_code", "N/A")
        response_text = getattr(e.response, "text", "No Content")
        logger.error(f"LLM API 请求失败 [{status_code}]: {e}\nURL: {LLM_API_URL}\nResponse: {response_text}")
        _consecutive_errors += 1
    except (KeyError, IndexError) as e:
        logger.error(f"LLM 响应解析失败: {e}\nURL: {LLM_API_URL}")
        _consecutive_errors += 1

    return ""


def extract_terms_from_text(text: str) -> dict[str, dict]:
    """
    调用 LLM 从一大段英文中自动提取合适的术语设定。
    返回格式: {"English Term": {"translation": "中文", "context": "语境"}}
    """
    if not LLM_API_KEY:
        logger.warning("LLM_API_KEY 未配置，无法提取术语")
        return {}
    
    system_prompt = (
        "You are an expert game translation terminology extractor.\n"
        "Analyze the following English text and extract key terms, proper nouns, character names, or special game vocabulary.\n"
        "For each term, provide a suitable Chinese translation and a brief context or condition under which this translation applies.\n"
        "Return the result STRICTLY as a JSON object without any other text.\n"
        "Example format:\n"
        "{\n"
        '  "Term in English": {"translation": "中文翻译", "context": "语境说明"}\n'
        "}\n"
    )
    
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text[:4000]},  # 截断以防止超长
        ],
        "temperature": 0.3,
    }
    
    url_to_call = LLM_API_URL.strip()
    if "api.deepseek.com" in url_to_call and not url_to_call.endswith("/completions"):
        url_to_call = "https://api.deepseek.com/chat/completions"
        
    try:
        resp = requests.post(url_to_call, headers=headers, json=payload, timeout=LLM_TIMEOUT * 2)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        
        # 清理可能存在的 markdown 代码块包裹
        if content.startswith("```"):
            content = content.replace("```json", "").replace("```", "").strip()
            
        import json
        result = json.loads(content)
        if isinstance(result, dict):
            return result
    except Exception as e:
        logger.error(f"AI 提取术语失败: {e}")
        
    return {}
