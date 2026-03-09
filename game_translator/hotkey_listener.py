"""
hotkey_listener.py - 全局热键监听
使用 keyboard 库监听用户自定义热键，线程安全回调
"""

import keyboard
import logging
import threading
from typing import Callable
from config import HOTKEY

logger = logging.getLogger(__name__)


class HotkeyListener:
    """全局热键监听器，注册热键并在触发时调用回调"""

    def __init__(self):
        self._callback: Callable | None = None
        self._current_hotkey: str = ""
        self._lock = threading.Lock()

    def register(self, hotkey: str, callback: Callable) -> bool:
        """
        注册热键
        :param hotkey: 热键字符串，例如 "ctrl+shift+t"
        :param callback: 触发时的回调函数
        :return: 是否注册成功
        """
        with self._lock:
            # 取消旧热键
            self._unregister_current()

            try:
                keyboard.add_hotkey(hotkey, self._on_trigger)
                self._callback = callback
                self._current_hotkey = hotkey
                logger.info(f"热键已注册: {hotkey}")
                print(f"[系统] 热键 '{hotkey}' 已注册成功并开始监听。")
                return True
            except Exception as e:
                logger.error(f"热键注册失败 [{hotkey}]: {e}")
                return False

    def _unregister_current(self):
        """取消当前热键（内部调用，需持锁）"""
        if self._current_hotkey:
            try:
                keyboard.remove_hotkey(self._current_hotkey)
                logger.debug(f"热键已取消: {self._current_hotkey}")
            except Exception:
                pass
            self._current_hotkey = ""
            self._callback = None

    def unregister(self):
        """取消当前热键"""
        with self._lock:
            self._unregister_current()

    def _on_trigger(self):
        """热键触发（在 keyboard 库线程中被调用）"""
        logger.debug(f"热键触发: {self._current_hotkey}")
        print(f"[触发] 检测到热键按下: {self._current_hotkey}")
        callback = self._callback
        if callback:
            # 在新线程中执行，避免阻塞 keyboard 监听线程
            threading.Thread(target=callback, daemon=True).start()

    @property
    def current_hotkey(self) -> str:
        return self._current_hotkey
