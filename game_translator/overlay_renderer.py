"""
overlay_renderer.py - 透明字幕覆盖层
无边框、全屏透明、始终置顶、点击穿透
字幕在指定位置显示，QTimer 自动消失
"""

import logging
from PyQt6.QtWidgets import QWidget, QLabel, QApplication
from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QFont, QColor, QPainter, QFontMetrics
import config
from config import (
    SUBTITLE_FONT_SIZE,
    SUBTITLE_FONT_COLOR, SUBTITLE_PADDING
)
import ctypes

logger = logging.getLogger(__name__)

# Windows API: 点击穿透
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
GWL_EXSTYLE = -20


class SubtitleItem:
    """单条字幕数据"""
    def __init__(self, text: str, box: list):
        self.text = text
        self.box = box   # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """返回 (x, y, width, height)"""
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        x = int(min(xs))
        y = int(min(ys))
        w = int(max(xs) - x)
        h = int(max(ys) - y)
        return x, y, w, h


class OverlayRenderer(QWidget):
    """透明字幕覆盖层窗口"""

    def __init__(self):
        super().__init__()
        self._subtitles: list[SubtitleItem] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._clear_subtitles)
        self._setup_window()

    def _setup_window(self):
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.hide()

    def show_subtitles(self, subtitles: list[SubtitleItem]):
        """
        显示字幕列表并启动自动消失计时器

        :param subtitles: SubtitleItem 列表
        """
        self._subtitles = subtitles
        self._timer.stop()
        self.update()
        self.show()
        self._make_click_through()
        self._timer.start(int(config.SUBTITLE_DURATION * 1000))
        logger.debug(f"显示字幕 {len(subtitles)} 条")

    def _clear_subtitles(self):
        """计时器超时，清除字幕"""
        self._subtitles = []
        self.hide()

    def _make_click_through(self):
        """设置 Windows 点击穿透"""
        try:
            hwnd = int(self.winId())
            ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            )
        except Exception as e:
            logger.warning(f"设置点击穿透失败: {e}")

    def paintEvent(self, event):
        if not self._subtitles:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont("Microsoft YaHei", SUBTITLE_FONT_SIZE, QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)

        drawn_rects = []
        ratio = self.devicePixelRatioF()

        for item in self._subtitles:
            x, y, bw, bh = item.rect
            # OCR 返回的坐标是物理像素，而 PyQt QWidget 绘制需要逻辑像素，因此要除以缩放比例
            x = int(x / ratio)
            y = int(y / ratio)
            bw = int(bw / ratio)
            bh = int(bh / ratio)
            text = item.text

            # 计算文本尺寸
            # 如果文字太长，限制最大宽度并允许多行
            max_w = min(800, max(bw, 300))
            text_rect = fm.boundingRect(0, 0, max_w, 2000, Qt.TextFlag.TextWordWrap, text)
            tw = text_rect.width() + SUBTITLE_PADDING * 2
            th = text_rect.height() + SUBTITLE_PADDING * 2

            # 尽量覆盖原文位置（居中对齐）
            draw_x = x + (bw - text_rect.width()) // 2
            draw_y = y  # 覆盖在原文上方

            # 碰撞检测，防止文字叠在一起
            bg_rect = QRect(draw_x, draw_y, tw, th)
            safe = False
            attempts = 0
            while not safe and attempts < 10:
                safe = True
                for rect in drawn_rects:
                    if bg_rect.intersects(rect):
                        # 如果有重叠，整体往下移
                        bg_rect.translate(0, rect.bottom() - bg_rect.top() + 2)
                        safe = False
                        break
                attempts += 1
            
            drawn_rects.append(bg_rect)

            # 背景框（圆角）
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bg_rect, 6, 6)

            # 文字
            painter.setPen(QColor(SUBTITLE_FONT_COLOR))
            # 绘制多行文本
            text_draw_rect = QRect(
                bg_rect.x() + SUBTITLE_PADDING,
                bg_rect.y() + SUBTITLE_PADDING,
                text_rect.width(),
                text_rect.height()
            )
            painter.drawText(text_draw_rect, Qt.TextFlag.TextWordWrap, text)

        painter.end()
