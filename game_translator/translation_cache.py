"""
translation_cache.py - 翻译缓存系统
使用字典缓存，持久化到 translation_cache.json
"""

import json
import logging
import threading
from pathlib import Path
from config import TRANSLATION_CACHE_FILE

logger = logging.getLogger(__name__)

_cache: dict[str, str] = {}
_lock = threading.Lock()


def load_translation_cache() -> None:
    """程序启动时加载缓存文件"""
    global _cache
    path = Path(TRANSLATION_CACHE_FILE)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            logger.info(f"已加载翻译缓存：{len(_cache)} 条")
        except Exception as e:
            logger.error(f"加载翻译缓存失败: {e}")
            _cache = {}
    else:
        _cache = {}


def save_translation_cache() -> None:
    """将当前缓存持久化到文件"""
    path = Path(TRANSLATION_CACHE_FILE)
    with _lock:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_cache, f, ensure_ascii=False, indent=2)
            logger.debug(f"翻译缓存已保存：{len(_cache)} 条")
        except Exception as e:
            logger.error(f"保存翻译缓存失败: {e}")


def get_cached_translation(text: str) -> str | None:
    """
    查询缓存
    :param text: 原文（英文）
    :return: 缓存的中文译文，未命中返回 None
    """
    with _lock:
        return _cache.get(text.strip())


def set_cached_translation(text: str, translation: str) -> None:
    """
    写入缓存并触发异步保存
    :param text: 原文
    :param translation: 译文
    """
    with _lock:
        _cache[text.strip()] = translation
    # 异步保存，避免阻塞主线程
    threading.Thread(target=save_translation_cache, daemon=True).start()


def get_cache_size() -> int:
    """返回当前缓存条数"""
    with _lock:
        return len(_cache)
