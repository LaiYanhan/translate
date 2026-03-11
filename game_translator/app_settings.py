"""
app_settings.py - 应用程序设置持久化（保存/读取 app_settings.json）
存储 LLM API 配置等运行时可修改的设置
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SETTINGS_FILE = Path(__file__).parent / "app_settings.json"

# 默认设置
_DEFAULTS = {
    "api_key": "",
    "api_url": "https://api.openai.com/v1/chat/completions",
    "api_model": "gpt-4o-mini",
    "subtitle_duration": 6.0,
    "subtitle_font_size": 22,
    "source_lang": "en",
    "target_lang": "zh",
}


def load_settings() -> dict:
    """从 app_settings.json 读取设置，不存在时返回默认值"""
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 补全缺失的键
            return {**_DEFAULTS, **data}
        except Exception as e:
            logger.error(f"读取设置失败: {e}")
    return dict(_DEFAULTS)


def save_settings(settings: dict) -> None:
    """将设置写入 app_settings.json"""
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        logger.info("应用设置已保存")
    except Exception as e:
        logger.error(f"保存设置失败: {e}")
