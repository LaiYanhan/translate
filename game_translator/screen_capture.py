"""
screen_capture.py - 截图模块
支持：指定窗口、框选区域、全屏三种模式
"""

import numpy as np
import mss
import mss.tools
import win32gui
import win32con
import win32ui
import win32api
import ctypes
from ctypes import windll
from PyQt6.QtWidgets import QApplication, QWidget, QRubberBand
from PyQt6.QtCore import Qt, QRect, QPoint, QSize
from PyQt6.QtGui import QColor, QPainter, QPixmap
import logging

logger = logging.getLogger(__name__)


# ==================== 全屏截图 ====================

def capture_screen() -> np.ndarray:
    """截取整个屏幕，返回 BGR numpy 数组"""
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 仅截取主显示器，防止多显示器导致画面拉伸过大
        screenshot = sct.grab(monitor)
        img = np.array(screenshot)
        # mss 返回 BGRA，转换为 BGR
        img = img[:, :, :3]
    return img


# ==================== 指定区域截图 ====================

def capture_region(region: dict) -> np.ndarray:
    """
    截取指定区域
    :param region: {"top": y, "left": x, "width": w, "height": h}
    :return: BGR numpy 数组
    """
    with mss.mss() as sct:
        screenshot = sct.grab(region)
        img = np.array(screenshot)
        img = img[:, :, :3]
    return img


# ==================== 指定窗口截图 ====================

def capture_window(hwnd: int) -> np.ndarray | None:
    """
    截取指定窗口（句柄），兼容被遮挡的窗口
    :param hwnd: 窗口句柄
    :return: BGR numpy 数组，失败返回 None
    """
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None

        # 使用 PrintWindow 确保能截取被遮挡窗口
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        # PW_RENDERFULLCONTENT = 2 (Windows 8.1+)
        result = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
        if not result:
            logger.warning("PrintWindow 失败，回退到 BitBlt")
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

        bmp_info = bitmap.GetInfo()
        bmp_str = bitmap.GetBitmapBits(True)
        img = np.frombuffer(bmp_str, dtype=np.uint8).reshape(
            bmp_info["bmHeight"], bmp_info["bmWidth"], 4
        )
        img = img[:, :, :3]   # 去掉 Alpha

        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return img
    except Exception as e:
        logger.error(f"capture_window 失败: {e}")
        return None


# ==================== 枚举可见窗口 ====================

def list_windows() -> list[tuple[int, str]]:
    """
    返回所有可见窗口列表
    :return: [(hwnd, title), ...]
    """
    windows = []

    def enum_callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows.append((hwnd, title))

    win32gui.EnumWindows(enum_callback, None)
    return windows


# ==================== 框选区域 UI ====================

class RegionSelector(QWidget):
    """全屏透明覆盖层，用户可拖动鼠标选择区域"""

    def __init__(self, callback):
        """
        :param callback: 选择完成后的回调，接收 (x, y, width, height)
        """
        super().__init__()
        self.callback = callback
        self.origin = QPoint()
        self.rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._setup_window()

    def _setup_window(self):
        # 全屏、无边框、透明、置顶
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.pos()
            self.rubber_band.setGeometry(QRect(self.origin, QSize()))
            self.rubber_band.show()

    def mouseMoveEvent(self, event):
        if not self.origin.isNull():
            self.rubber_band.setGeometry(
                QRect(self.origin, event.pos()).normalized()
            )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            rect = QRect(self.origin, event.pos()).normalized()
            self.rubber_band.hide()
            self.close()
            if rect.width() > 10 and rect.height() > 10:
                # PyQt events are in logical pixels, mss expects physical pixels
                ratio = self.devicePixelRatioF()
                px = int(rect.x() * ratio)
                py = int(rect.y() * ratio)
                pw = int(rect.width() * ratio)
                ph = int(rect.height() * ratio)
                self.callback(px, py, pw, ph)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
