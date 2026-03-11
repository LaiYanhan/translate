"""
main.py - 游戏实时翻译工具主入口
主控制窗口 + 翻译流水线
"""

import sys
import logging
import threading
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QGroupBox, QStatusBar,
    QInputDialog, QMessageBox, QListWidget, QListWidgetItem,
    QLineEdit, QScrollArea, QDoubleSpinBox, QSpinBox, QPlainTextEdit, QDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt6.QtGui import QFont, QIcon, QColor, QTextCursor

import config
from config import CaptureMode, HOTKEY
from screen_capture import (
    capture_screen, capture_region, capture_window,
    list_windows, RegionSelector
)
from ocr_engine import ocr_engine
from ocr_postprocess import merge_ocr_lines
from subtitle_detector import detect_subtitle_region, filter_subtitle_results
from translator import translate_text
from translation_cache import load_translation_cache, get_cache_size, clear_cache
from overlay_renderer import OverlayRenderer, SubtitleItem
from hotkey_listener import HotkeyListener
from terminology_manager import TerminologyManagerDialog
from app_settings import load_settings, save_settings

# ==================== 日志窗口 ====================
class LogWindow(QDialog):
    """独立的日志查看窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("运行日志 - Game Translator")
        self.resize(600, 400)
        self.setStyleSheet("background: #1e1e2e; color: #cdd6f4;")
        
        layout = QVBoxLayout(self)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("""
            background: #181825; color: #a6adc8; 
            font-family: 'Consolas', 'Monaco', monospace; font-size: 11px;
            border: 1px solid #313244; border-radius: 4px; padding: 5px;
        """)
        layout.addWidget(self.console)
        
        btn_clear = QPushButton("清除日志")
        btn_clear.clicked.connect(self.console.clear)
        btn_clear.setFixedWidth(100)
        layout.addWidget(btn_clear, alignment=Qt.AlignmentFlag.AlignRight)

    def append_log(self, text: str):
        self.console.appendPlainText(text)
        self.console.moveCursor(QTextCursor.MoveOperation.End)


# ==================== 日志捕获 ====================
class LogSignal(QObject):
    new_log = pyqtSignal(str)

log_signal = LogSignal()

class GUILogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        log_signal.new_log.emit(msg)

# 全局配置日志
gui_handler = GUILogHandler()
gui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout), gui_handler],
)
logger = logging.getLogger(__name__)


# ==================== 翻译工作线程 ====================

class TranslationWorker(QThread):
    """在后台线程执行截图→OCR→翻译流水线"""

    finished = pyqtSignal(list)      # [(translated_text, box), ...]
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, mode: str, hwnd: int | None, region: dict | None):
        super().__init__()
        self.mode = mode
        self.hwnd = hwnd
        self.region = region
        self._subtitle_region: dict | None = None

    def run(self):
        try:
            # ----- 截图 -----
            self.status.emit("正在截图...")
            image = self._capture()
            if image is None or getattr(image, 'size', 0) == 0:
                self.error.emit("截图失败，获取到的画面为空，请重新选择正确的区域或窗口。")
                return
            
            # --- 强制保存当前截图以便调试游戏全屏穿透问题 ---
            try:
                import cv2
                cv2.imwrite("debug_capture.png", image)
            except Exception as e:
                logger.warning(f"无法保存 debug_capture.png: {e}")

            h, w = image.shape[:2]

            # ----- 全屏 OCR（用于字幕区域检测） -----
            self.status.emit("正在 OCR 识别...")
            raw_results = ocr_engine.recognize(image)

            if not raw_results:
                self.status.emit("未识别到任何文字。已保存截图到 debug_capture.png 等待排查。")
                try:
                    import cv2
                    cv2.imwrite("debug_capture.png", image)
                except Exception as e:
                    logger.warning(f"无法保存 debug_capture.png: {e}")
                self.finished.emit([])
                return
            else :
                try:
                    import cv2
                    cv2.imwrite("debug_capture_ocr.png", image)
                except Exception as e:
                    logger.warning(f"无法保存 debug_capture_ocr.png: {e}")

            # ----- 字幕区域检测（可选） -----
            # （用户已要求完全移除自动字幕过滤功能，现将所有识别到的文字全部保留）

            # ----- 座标轴平移修复 (转换为屏幕绝对坐标) -----
            # 无论什么模式截得的图，此时 raw_results 的坐标都是相对于这块 image 的左上角的
            if self.mode == CaptureMode.REGION and self.region:
                raw_results = _offset_boxes(raw_results, self.region["left"], self.region["top"])
            elif self.mode == CaptureMode.WINDOW and self.hwnd:
                import win32gui
                try:
                    w_left, w_top, w_right, w_bottom = win32gui.GetWindowRect(self.hwnd)
                    raw_results = _offset_boxes(raw_results, w_left, w_top)
                except Exception as e:
                    logger.warning(f"获取窗口坐标失败: {e}")

            # ----- 文本合并 -----
            merged = merge_ocr_lines(raw_results)

            if not merged:
                self.status.emit("未合并到有效文本。")
                self.finished.emit([])
                return

            # ----- 翻译 -----
            self.status.emit(f"正在翻译 {len(merged)} 条文本...")
            results = []
            
            import translator
            translator.reset_errors()
            
            print(f"\n[系统] 开始翻译 {len(merged)} 条文本...")
            for text, box, conf in merged:
                translation = translate_text(text)
                if translation:
                    print(f"[翻译结果] {text} -> {translation}")
                    results.append((translation, box))

            self.finished.emit(results)
            self.status.emit(f"翻译完成，共 {len(results)} 条。")

        except Exception as e:
            logger.exception("翻译流水线异常")
            self.error.emit(f"错误: {e}")

    def _capture(self):
        if self.mode == CaptureMode.WINDOW and self.hwnd:
            return capture_window(self.hwnd)
        elif self.mode == CaptureMode.REGION and self.region:
            return capture_region(self.region)
        else:
            return capture_screen()


# ==================== 辅助函数 ====================

def _crop_region(image, region: dict):
    """从图像裁剪指定区域"""
    import numpy as np
    t = region["top"]
    l = region["left"]
    b = t + region["height"]
    r = l + region["width"]
    return image[t:b, l:r]


def _offset_boxes(results, dx, dy):
    """将 OCR box 坐标偏移（裁剪区域坐标转全屏坐标）"""
    offset_results = []
    for text, box, conf in results:
        new_box = [[p[0] + dx, p[1] + dy] for p in box]
        offset_results.append((text, new_box, conf))
    return offset_results


# ==================== 窗口选择对话框 ====================

class WindowSelectDialog(QWidget):
    """弹窗列出所有可见窗口，用户选择目标游戏窗口"""

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback
        self.setWindowTitle("选择游戏窗口")
        self.setMinimumSize(400, 300)
        self._windows = list_windows()
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("background:#1e1e2e; color:#cdd6f4;")
        layout = QVBoxLayout(self)
        label = QLabel("请选择游戏窗口：")
        label.setStyleSheet("font-size:14px; color:#cba6f7; margin-bottom:6px;")
        layout.addWidget(label)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "background:#181825; color:#cdd6f4; border:1px solid #313244;"
        )
        for hwnd, title in self._windows:
            item = QListWidgetItem(f"[{hwnd}] {title}")
            item.setData(Qt.ItemDataRole.UserRole, hwnd)
            self.list_widget.addItem(item)
        self.list_widget.doubleClicked.connect(self._select)
        layout.addWidget(self.list_widget)

        btn = QPushButton("确认选择")
        btn.setStyleSheet("background:#cba6f7; color:#1e1e2e; padding:6px; border-radius:4px;")
        btn.clicked.connect(self._select)
        layout.addWidget(btn)

    def _select(self):
        item = self.list_widget.currentItem()
        if item:
            hwnd = item.data(Qt.ItemDataRole.UserRole)
            title = item.text()
            self.callback(hwnd, title)
            self.close()


# ==================== 主控制窗口 ====================

class MainWindow(QMainWindow):

    _translate_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Translator - 游戏实时翻译工具")
        self.setMinimumSize(480, 680)

        # 状态
        self._mode = CaptureMode.FULLSCREEN
        self._hwnd: int | None = None
        self._window_title: str = ""
        self._region: dict | None = None
        self._hotkey = HOTKEY
        self._listening = False

        # 子系统
        self._overlay = OverlayRenderer()
        self._hotkey_listener = HotkeyListener()
        self._log_window = LogWindow(self) # 创建日志窗口
        self._worker: TranslationWorker | None = None
        self._region_selector: RegionSelector | None = None
        self._window_select: WindowSelectDialog | None = None

        self._setup_ui()
        self._apply_stylesheet()

        # 连接日志信号到独立窗口
        log_signal.new_log.connect(self._log_window.append_log)

        # 加载设置
        self._load_app_settings()
        # 加载翻译缓存
        from translation_cache import load_translation_cache
        load_translation_cache()
        
        # 初始化 OCR（后台线程，避免阻塞 UI）
        import threading
        from ocr_engine import ocr_engine
        threading.Thread(target=ocr_engine.initialize, daemon=True).start()

        self._refresh_info()

    # ---------- UI 搭建 ----------

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root_layout.addWidget(scroll)

        main_widget = QWidget()
        scroll.setWidget(main_widget)

        root = QVBoxLayout(main_widget)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # 标题
        title = QLabel("🎮 Game Translator")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:22px; font-weight:bold; color:#cba6f7; margin-bottom:4px;")
        root.addWidget(title)

        subtitle = QLabel("游戏实时翻译工具")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size:12px; color:#a6adc8;")
        root.addWidget(subtitle)

        # 查看日志按钮
        self._btn_show_log = QPushButton("📜 查看运行日志 (Logs)")
        self._btn_show_log.setFixedWidth(200)
        self._btn_show_log.setObjectName("logBtn")
        self._btn_show_log.clicked.connect(self._log_window.show)
        root.addWidget(self._btn_show_log, alignment=Qt.AlignmentFlag.AlignCenter)

        # 截图模式
        capture_group = QGroupBox("截图模式")
        capture_group.setObjectName("captureGroup")
        capture_layout = QVBoxLayout(capture_group)
        
        self._lbl_mode = QLabel("📷 截图模式：全屏")
        self._lbl_window = QLabel("🪟 目标窗口：未选择")
        self._lbl_hotkey = QLabel(f"⌨ 快捷键：{self._hotkey}")
        
        capture_layout.addWidget(self._lbl_mode)
        capture_layout.addWidget(self._lbl_window)
        capture_layout.addWidget(self._lbl_hotkey)

        mode_buttons_layout = QHBoxLayout()
        btn_fullscreen = QPushButton("全屏")
        btn_fullscreen.clicked.connect(lambda: self._set_mode(CaptureMode.FULLSCREEN))
        btn_window = QPushButton("选择窗口")
        btn_window.clicked.connect(lambda: self._set_mode(CaptureMode.WINDOW))
        btn_region = QPushButton("框选区域")
        btn_region.clicked.connect(lambda: self._set_mode(CaptureMode.REGION))
        mode_buttons_layout.addWidget(btn_fullscreen)
        mode_buttons_layout.addWidget(btn_window)
        mode_buttons_layout.addWidget(btn_region)
        capture_layout.addLayout(mode_buttons_layout)

        btn_change_hotkey = QPushButton("修改热键")
        btn_change_hotkey.clicked.connect(self._change_hotkey)
        capture_layout.addWidget(btn_change_hotkey)
        
        root.addWidget(capture_group)

        # 翻译控制
        control_group = QGroupBox("翻译控制")
        control_layout = QVBoxLayout(control_group)

        self._btn_listen = QPushButton("▶ 启动监听")
        self._btn_listen.setObjectName("listenBtn")
        self._btn_listen.clicked.connect(self._toggle_listen)
        control_layout.addWidget(self._btn_listen)

        btn_manual_translate = QPushButton("手动翻译一次")
        btn_manual_translate.clicked.connect(self._trigger_translation)
        control_layout.addWidget(btn_manual_translate)

        root.addWidget(control_group)

        # API 设置
        api_box = QGroupBox("API 设置")
        api_layout = QVBoxLayout(api_box)

        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(QLabel("API Key:"))
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("填写你的 LLM API Key")
        api_key_layout.addWidget(self._api_key_input)
        api_layout.addLayout(api_key_layout)

        api_url_layout = QHBoxLayout()
        api_url_layout.addWidget(QLabel("API URL:"))
        self._api_url_input = QLineEdit()
        self._api_url_input.setPlaceholderText("例如: https://api.openai.com/v1/chat/completions")
        api_url_layout.addWidget(self._api_url_input)
        api_layout.addLayout(api_url_layout)

        api_model_layout = QHBoxLayout()
        api_model_layout.addWidget(QLabel("模型名称:"))
        self._api_model_input = QLineEdit()
        self._api_model_input.setPlaceholderText("例如: gpt-4o-mini")
        api_model_layout.addWidget(self._api_model_input)
        api_layout.addLayout(api_model_layout)

        btn_save_api = QPushButton("保存 API 设置")
        btn_save_api.setObjectName("saveApiBtn")
        btn_save_api.clicked.connect(self._save_api_settings)
        api_layout.addWidget(btn_save_api)

        root.addWidget(api_box)

        # 通用设置
        general_settings_group = QGroupBox("通用设置")
        general_settings_layout = QVBoxLayout(general_settings_group)

        # 字幕显示时长
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("字幕显示时长 (秒):"))
        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setRange(1.0, 30.0)
        self._duration_spin.setSingleStep(0.5)
        self._duration_spin.valueChanged.connect(self._save_general_settings)
        duration_layout.addWidget(self._duration_spin)
        general_settings_layout.addLayout(duration_layout)

        # 字幕字体大小
        font_size_layout = QHBoxLayout()
        font_size_layout.addWidget(QLabel("字幕字体大小 (px):"))
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 60)
        self._font_size_spin.setSingleStep(1)
        self._font_size_spin.valueChanged.connect(self._save_general_settings)
        font_size_layout.addWidget(self._font_size_spin)
        general_settings_layout.addLayout(font_size_layout)

        # 源语言
        source_lang_layout = QHBoxLayout()
        source_lang_layout.addWidget(QLabel("源语言 (OCR):"))
        self._source_lang_combo = QComboBox()
        self._source_lang_map = {
            "English (en)": "en",
            "中英混合 (ch)": "ch",
            "Japanese (japan)": "japan",
            "Korean (korea)": "korea",
            "French (french)": "french",
            "German (german)": "german",
        }
        self._source_lang_combo.addItems(list(self._source_lang_map.keys()))
        self._source_lang_combo.currentIndexChanged.connect(self._save_general_settings)
        source_lang_layout.addWidget(self._source_lang_combo)
        general_settings_layout.addLayout(source_lang_layout)

        # 目标语言
        target_lang_layout = QHBoxLayout()
        target_lang_layout.addWidget(QLabel("目标语言 (翻译):"))
        self._target_lang_combo = QComboBox()
        self._target_lang_list = [
            "简体中文", "繁體中文", "English", "日本語", "Korean", "French", "German"
        ]
        self._target_lang_combo.addItems(self._target_lang_list)
        self._target_lang_combo.currentIndexChanged.connect(self._save_general_settings)
        target_lang_layout.addWidget(self._target_lang_combo)
        general_settings_layout.addLayout(target_lang_layout)

        root.addWidget(general_settings_group)

        # 术语管理
        terminology_group = QGroupBox("术语管理")
        terminology_layout = QVBoxLayout(terminology_group)
        btn_terminology = QPushButton("管理自定义术语")
        btn_terminology.clicked.connect(self._open_terminology)
        terminology_layout.addWidget(btn_terminology)
        root.addWidget(terminology_group)

        # 信息显示
        info_group = QGroupBox("状态信息")
        info_layout = QVBoxLayout(info_group)
        self._lbl_ocr = QLabel("🔍 OCR 模式：未初始化")
        self._lbl_cache = QLabel("💾 翻译缓存：0 条")
        info_layout.addWidget(self._lbl_ocr)
        info_layout.addWidget(self._lbl_cache)
        root.addWidget(info_group)

        # 底部按钮
        bottom_buttons_layout = QHBoxLayout()
        btn_clear_cache = QPushButton("清空缓存")
        btn_clear_cache.setObjectName("clearBtn")
        btn_clear_cache.clicked.connect(self._clear_cache)
        bottom_buttons_layout.addWidget(btn_clear_cache)

        btn_quit = QPushButton("退出")
        btn_quit.setObjectName("quitBtn")
        btn_quit.clicked.connect(self.close)
        bottom_buttons_layout.addWidget(btn_quit)
        root.addLayout(bottom_buttons_layout)

        # 状态栏
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("就绪")
        self.setStatusBar(self.status_bar)

    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow { background: #1e1e2e; }
            QWidget { background: #1e1e2e; color: #cdd6f4; font-family: "Microsoft YaHei"; }
            QGroupBox {
                border: 1px solid #313244; border-radius: 8px;
                margin-top: 8px; padding: 8px 4px 4px 4px; color: #a6adc8;
                font-size: 13px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #cba6f7; }
            QPushButton {
                background: #45475a; color: #cdd6f4; border: none;
                padding: 8px 16px; border-radius: 6px; font-size: 13px;
            }
            QPushButton:hover { background: #7f849c; }
            QPushButton#listenBtn { background: #a6e3a1; color: #1e1e2e; font-weight: bold; }
            QPushButton#listenBtn:hover { background: #94e2d5; }
            QPushButton#quitBtn { background: #f38ba8; color: #1e1e2e; }
            QPushButton#quitBtn:hover { background: #eba0ac; }
            QPushButton#clearBtn { background: #fab387; color: #1e1e2e; }
            QPushButton#clearBtn:hover { background: #f9e2af; }
            QPushButton#saveApiBtn { background: #89b4fa; color: #1e1e2e; font-weight: bold; }
            QPushButton#saveApiBtn:hover { background: #b4befe; }
            QPushButton#logBtn { background: #45475a; color: #cdd6f4; border: 1px solid #585b70; }
            QPushButton#logBtn:hover { background: #585b70; }
            QGroupBox { font-weight: bold; color: #89b4fa; border: 1px solid #313244; 
                        margin-top: 10px; padding-top: 10px; border-radius: 6px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLineEdit {
                background: #313244; color: #cdd6f4;
                border: 1px solid #585b70; padding: 5px 8px;
                border-radius: 5px; font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #cba6f7; }
            QStatusBar { background: #181825; color: #a6adc8; font-size: 12px; }
        """)

    # ---------- 逻辑 ----------

    def _refresh_info(self):
        mode_labels = {
            CaptureMode.FULLSCREEN: "🖥 全屏",
            CaptureMode.WINDOW: "🪟 指定窗口",
            CaptureMode.REGION: "✂ 框选区域",
        }
        self._lbl_mode.setText(f"📷 截图模式：{mode_labels.get(self._mode, self._mode)}")
        self._lbl_window.setText(f"🪟 目标窗口：{self._window_title or '未选择'}")
        self._lbl_hotkey.setText(f"⌨ 快捷键：{self._hotkey}")
        self._lbl_ocr.setText("🔍 OCR 模式：初始化中..." if not ocr_engine._initialized
                               else "🔍 OCR 模式：已就绪")
        self._lbl_cache.setText(f"💾 翻译缓存：{get_cache_size()} 条")
        # API 状态
        api_ok = bool(config.LLM_API_KEY)
        api_hint = "✅ 已配置" if api_ok else "⚠ 未配置（请填写 API Key）"
        self._lbl_mode.setToolTip(f"API 状态：{api_hint}")

    def _clear_cache(self):
        """确认并清空翻译缓存"""
        reply = QMessageBox.question(
            self, "清空缓存", "确定要清空所有翻译快照缓存吗？\n这将删除已保存的翻译记录，下次翻译将重新请求服务器。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            clear_cache()
            self._refresh_info()
            self.status_bar.showMessage("翻译缓存已清空。")

    def _set_mode(self, mode: str):
        self._mode = mode
        if mode == CaptureMode.WINDOW:
            self._window_select = WindowSelectDialog(self._on_window_selected, self)
            self._window_select.show()
        elif mode == CaptureMode.REGION:
            self._region_selector = RegionSelector(self._on_region_selected)
            self._region_selector.show()
        self._refresh_info()

    def _on_window_selected(self, hwnd: int, title: str):
        self._hwnd = hwnd
        self._window_title = title
        self._refresh_info()
        self.status_bar.showMessage(f"已选择窗口: {title}")

    def _on_region_selected(self, x: int, y: int, w: int, h: int):
        self._region = {"top": y, "left": x, "width": w, "height": h}
        self.status_bar.showMessage(f"已框选区域: ({x},{y}) {w}×{h}")
        self._refresh_info()

    def _toggle_listen(self):
        if not self._listening:
            ok = self._hotkey_listener.register(self._hotkey, self._trigger_translation)
            if ok:
                self._listening = True
                self._btn_listen.setText("⏹ 停止监听")
                self._btn_listen.setStyleSheet(
                    "background:#f38ba8; color:#1e1e2e; font-weight:bold;"
                    "padding:8px 16px; border-radius:6px;"
                )
                self.status_bar.showMessage(f"监听中，热键: {self._hotkey}")
        else:
            self._hotkey_listener.unregister()
            self._listening = False
            self._btn_listen.setText("▶ 启动监听")
            self._btn_listen.setStyleSheet("")
            self.status_bar.showMessage("已停止监听")

    def _trigger_translation(self):
        """热键触发或手动按钮触发翻译"""
        if self._worker and self._worker.isRunning():
            logger.debug("上次翻译仍在进行中，跳过")
            return

        self.status_bar.showMessage("翻译中...")
        self._worker = TranslationWorker(self._mode, self._hwnd, self._region)
        self._worker.finished.connect(self._on_translation_done)
        self._worker.error.connect(lambda msg: self.status_bar.showMessage(msg))
        self._worker.status.connect(lambda msg: self.status_bar.showMessage(msg))
        self._worker.start()

    def _on_translation_done(self, results: list):
        """翻译完成回调，在主线程更新字幕"""
        self._refresh_info()
        if not results:
            self.status_bar.showMessage("未检测到可翻译文字。")
            return

        subtitles = [SubtitleItem(text, box) for text, box in results]
        self._overlay.show_subtitles(subtitles)
        self.status_bar.showMessage(f"已显示 {len(subtitles)} 条字幕（{config.SUBTITLE_DURATION}s 后消失）")

    def _load_app_settings(self):
        """同步读取设置到 UI 并注入运行时配置"""
        s = load_settings()
        
        # 1. 填充 API UI 并注入全局 Config
        api_key = s.get("api_key", "")
        api_url = s.get("api_url", "https://api.openai.com/v1/chat/completions")
        api_model = s.get("api_model", "gpt-4o-mini")
        
        self._api_key_input.setText(api_key)
        self._api_url_input.setText(api_url)
        self._api_model_input.setText(api_model)

        config.LLM_API_KEY = api_key
        config.LLM_API_URL = api_url
        config.LLM_MODEL   = api_model

        # 同步更新 translator 模块引用
        import translator as _tr
        _tr.LLM_API_KEY = config.LLM_API_KEY
        _tr.LLM_API_URL = config.LLM_API_URL
        _tr.LLM_MODEL   = config.LLM_MODEL
        
        # 2. 常规设置
        duration = s.get("subtitle_duration", 6.0)
        self._duration_spin.setValue(float(duration))
        config.SUBTITLE_DURATION = float(duration)

        font_size = s.get("subtitle_font_size", 22)
        self._font_size_spin.setValue(int(font_size))
        config.SUBTITLE_FONT_SIZE = int(font_size)

        src_l = s.get("source_lang", "en")
        for label, code in self._source_lang_map.items():
            if code == src_l:
                self._source_lang_combo.setCurrentText(label)
                break
        config.SOURCE_LANG = src_l
        config.OCR_LANG = src_l

        tgt_l = s.get("target_lang", "简体中文")
        # 兼容旧版的 "zh" -> "简体中文"
        if tgt_l == "zh": tgt_l = "简体中文"
        self._target_lang_combo.setCurrentText(tgt_l)
        config.TARGET_LANG = tgt_l

    def _save_api_settings(self):
        """将输入框内容保存到 app_settings.json 并即时生效"""
        key = self._api_key_input.text().strip()
        url = self._api_url_input.text().strip()
        model = self._api_model_input.text().strip()

        # 自动修正 DeepSeek 的 404 URL 错误
        if "api.deepseek.com" in url and not url.endswith("/completions"):
            url = "https://api.deepseek.com/chat/completions"
            self._api_url_input.setText(url)

        settings = {
            "api_key": key,
            "api_url": url or "https://api.openai.com/v1/chat/completions",
            "api_model": model or "gpt-4o-mini",
        }
        save_settings(settings)

        # 即时更新运行时 config，无需重启
        config.LLM_API_KEY = settings["api_key"]
        config.LLM_API_URL = settings["api_url"]
        config.LLM_MODEL   = settings["api_model"]

        # 同步更新 translator 模块引用
        import translator as _tr
        _tr.LLM_API_KEY = config.LLM_API_KEY
        _tr.LLM_API_URL = config.LLM_API_URL
        _tr.LLM_MODEL   = config.LLM_MODEL

        masked = self._mask_key(key)
        self.status_bar.showMessage(
            f"API 设置已保存 | Key: {masked} | URL: {settings['api_url']} | Model: {settings['api_model']}"
        )
        self._refresh_info()

    def _save_general_settings(self):
        s = load_settings()
        s["subtitle_duration"] = self._duration_spin.value()
        s["subtitle_font_size"] = self._font_size_spin.value()
        
        src_label = self._source_lang_combo.currentText()
        src_code = self._source_lang_map.get(src_label, "en")
        s["source_lang"] = src_code
        
        tgt_lang = self._target_lang_combo.currentText()
        s["target_lang"] = tgt_lang

        save_settings(s)
        
        # 同步更新 config
        config.SUBTITLE_DURATION = s["subtitle_duration"]
        config.SUBTITLE_FONT_SIZE = s["subtitle_font_size"]
        config.SOURCE_LANG = s["source_lang"]
        config.OCR_LANG = s["source_lang"]
        config.TARGET_LANG = s["target_lang"]

        self.status_bar.showMessage(
            f"已保存设置: {src_code} ➡ {tgt_lang} | 字幕 {s['subtitle_duration']}s"
        )
        self._refresh_info()

    @staticmethod
    def _mask_key(key: str) -> str:
        """显示脱敏 Key（只显示前4位和后4位）"""
        if len(key) <= 8:
            return "****" if key else "（空）"
        return f"{key[:4]}...{key[-4:]}"

    def _open_terminology(self):
        dialog = TerminologyManagerDialog(self)
        dialog.exec()

    def _change_hotkey(self):
        text, ok = QInputDialog.getText(
            self, "修改热键", "请输入新热键（例如 ctrl+shift+t）：",
            text=self._hotkey
        )
        if ok and text.strip():
            was_listening = self._listening
            if was_listening:
                self._hotkey_listener.unregister()
            self._hotkey = text.strip()
            if was_listening:
                self._hotkey_listener.register(self._hotkey, self._trigger_translation)
            self._refresh_info()
            self.status_bar.showMessage(f"热键已更新: {self._hotkey}")

    def closeEvent(self, event):
        self._hotkey_listener.unregister()
        self._overlay.close()
        super().closeEvent(event)


# ==================== 入口 ====================

def main():
    # 强制应用程序使用物理像素 (High DPI Aware)，防止坐标随着缩放漂移
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except:
            pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
