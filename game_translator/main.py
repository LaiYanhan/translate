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
    QLineEdit, QScrollArea, QDoubleSpinBox, QSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QColor

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

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
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
        self._worker: TranslationWorker | None = None
        self._region_selector: RegionSelector | None = None
        self._window_select: WindowSelectDialog | None = None

        self._setup_ui()
        self._apply_stylesheet()

        # 加载设置
        self._load_app_settings()
        # 加载翻译缓存
        load_translation_cache()
        # 初始化 OCR（后台线程，避免阻塞 UI）
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

        # 信息面板
        info_box = QGroupBox("当前状态")
        info_layout = QVBoxLayout(info_box)
        self._lbl_mode = QLabel()
        self._lbl_window = QLabel()
        self._lbl_hotkey = QLabel()
        self._lbl_ocr = QLabel()
        self._lbl_cache = QLabel()
        for lbl in [self._lbl_mode, self._lbl_window, self._lbl_hotkey,
                    self._lbl_ocr, self._lbl_cache]:
            lbl.setStyleSheet("font-size:13px; color:#cdd6f4; padding: 2px 0;")
            info_layout.addWidget(lbl)
        root.addWidget(info_box)

        # 截图模式按钮
        capture_box = QGroupBox("截图模式")
        capture_layout = QHBoxLayout(capture_box)
        for label, mode in [
            ("🖥 全屏", CaptureMode.FULLSCREEN),
            ("🪟 指定窗口", CaptureMode.WINDOW),
            ("✂ 框选区域", CaptureMode.REGION),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, m=mode: self._set_mode(m))
            capture_layout.addWidget(btn)
        root.addWidget(capture_box)

        # 功能按钮
        func_box = QGroupBox("功能")
        func_layout = QVBoxLayout(func_box)

        row1 = QHBoxLayout()
        self._btn_listen = QPushButton("▶ 启动监听")
        self._btn_listen.clicked.connect(self._toggle_listen)
        self._btn_listen.setObjectName("listenBtn")
        row1.addWidget(self._btn_listen)

        btn_translate_now = QPushButton("⚡ 立即翻译")
        btn_translate_now.clicked.connect(self._trigger_translation)
        row1.addWidget(btn_translate_now)
        func_layout.addLayout(row1)

        row2 = QHBoxLayout()
        btn_term = QPushButton("📖 术语管理")
        btn_term.clicked.connect(self._open_terminology)
        row2.addWidget(btn_term)

        btn_hotkey = QPushButton("⌨ 修改热键")
        btn_hotkey.clicked.connect(self._change_hotkey)
        row2.addWidget(btn_hotkey)
        func_layout.addLayout(row2)

        row3 = QHBoxLayout()
        btn_clear = QPushButton("🧹 清空缓存")
        btn_clear.setObjectName("clearBtn")
        btn_clear.clicked.connect(self._clear_cache)
        row3.addWidget(btn_clear)

        btn_quit = QPushButton("❌ 退出")
        btn_quit.setObjectName("quitBtn")
        btn_quit.clicked.connect(self.close)
        row3.addWidget(btn_quit)
        func_layout.addLayout(row3)

        root.addWidget(func_box)

        # ---- 常规设置 ----
        settings_box = QGroupBox("⚙ 常规设置")
        settings_layout = QVBoxLayout(settings_box)
        settings_layout.setSpacing(10)

        # 停留时长 & 字体大小
        row_params = QHBoxLayout()
        row_params.addWidget(QLabel("字幕停留时长 (秒):"))
        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setRange(1.0, 60.0)
        self._duration_spin.setSingleStep(0.5)
        self._duration_spin.setValue(config.SUBTITLE_DURATION)
        self._duration_spin.valueChanged.connect(self._save_general_settings)
        self._duration_spin.setStyleSheet("background:#313244; color:#cdd6f4; border:1px solid #585b70; padding:4px;")
        row_params.addWidget(self._duration_spin)

        row_params.addSpacing(20)
        row_params.addWidget(QLabel("字幕字体大小:"))
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 100)
        self._font_size_spin.setValue(int(config.SUBTITLE_FONT_SIZE))
        self._font_size_spin.valueChanged.connect(self._save_general_settings)
        self._font_size_spin.setStyleSheet("background:#313244; color:#cdd6f4; border:1px solid #585b70; padding:4px;")
        row_params.addWidget(self._font_size_spin)
        row_params.addStretch()
        settings_layout.addLayout(row_params)

        # 语言选择
        row_langs = QHBoxLayout()
        row_langs.addWidget(QLabel("📖 源语言 (OCR):"))
        self._source_lang_combo = QComboBox()
        # PaddleOCR 支持的常用 key: en, ch, japan, korea, french, german
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
        row_langs.addWidget(self._source_lang_combo)

        row_langs.addSpacing(20)
        row_langs.addWidget(QLabel("➡ 翻译目标语言:"))
        self._target_lang_combo = QComboBox()
        self._target_lang_list = [
            "简体中文", "繁體中文", "English", "日本語", "Korean", "French", "German"
        ]
        self._target_lang_combo.addItems(self._target_lang_list)
        self._target_lang_combo.currentIndexChanged.connect(self._save_general_settings)
        row_langs.addWidget(self._target_lang_combo)
        row_langs.addStretch()
        settings_layout.addLayout(row_langs)

        root.addWidget(settings_box)

        # ---- API 设置面板 ----
        api_box = QGroupBox("🔑 API 设置")
        api_layout = QVBoxLayout(api_box)
        api_layout.setSpacing(6)

        # API Key
        api_layout.addWidget(QLabel("API Key："))
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("sk-xxxxxxxxxxxxxxxx")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setMinimumWidth(350)
        api_layout.addWidget(self._api_key_input)

        # API URL
        api_layout.addWidget(QLabel("API URL："))
        self._api_url_input = QLineEdit()
        self._api_url_input.setPlaceholderText("https://api.openai.com/v1/chat/completions")
        self._api_url_input.setMinimumWidth(350)
        api_layout.addWidget(self._api_url_input)

        # Model
        api_layout.addWidget(QLabel("Model："))
        self._api_model_input = QLineEdit()
        self._api_model_input.setPlaceholderText("gpt-4o-mini")
        self._api_model_input.setMinimumWidth(350)
        api_layout.addWidget(self._api_model_input)

        # 保存按钮
        save_api_btn = QPushButton("💾 保存 API 设置")
        save_api_btn.setObjectName("saveApiBtn")
        save_api_btn.clicked.connect(self._save_api_settings)
        api_layout.addWidget(save_api_btn)

        root.addWidget(api_box)

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
        """从持久化文件读取 设置并填入 UI"""
        s = load_settings()
        self._api_key_input.setText(s.get("llm_api_key", ""))
        self._api_url_input.setText(s.get("llm_api_url", ""))
        self._api_model_input.setText(s.get("llm_model", ""))
        
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
            "llm_api_key": key,
            "llm_api_url": url or "https://api.openai.com/v1/chat/completions",
            "llm_model": model or "gpt-4o-mini",
            "subtitle_duration": self._duration_spin.value()
        }
        save_settings(settings)

        # 即时更新运行时 config，无需重启
        config.LLM_API_KEY = settings["llm_api_key"]
        config.LLM_API_URL = settings["llm_api_url"]
        config.LLM_MODEL   = settings["llm_model"]

        # 同步更新 translator 模块引用
        import translator as _tr
        _tr.LLM_API_KEY = config.LLM_API_KEY
        _tr.LLM_API_URL = config.LLM_API_URL
        _tr.LLM_MODEL   = config.LLM_MODEL

        masked = self._mask_key(key)
        self.status_bar.showMessage(
            f"API 设置已保存 | Key: {masked} | URL: {settings['llm_api_url']} | Model: {settings['llm_model']}"
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
        config.OCR_LANG = s["source_lang"] # OCR 跟随源语言
        config.TARGET_LANG = s["target_lang"]

        self.status_bar.showMessage(
            f"设置已更新 | 时长:{config.SUBTITLE_DURATION}s | 字体:{config.SUBTITLE_FONT_SIZE}px | {src_code}➡{tgt_lang}"
        )

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
