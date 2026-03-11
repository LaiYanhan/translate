"""
config.py - 全局配置文件
LLM API 配置优先从 app_settings.json 读取（由主窗口 UI 保存），
其次读取环境变量，最后使用硬编码默认值。
"""

import os
from pathlib import Path

# ==================== 路径配置 ====================
BASE_DIR = Path(__file__).parent
TERMINOLOGY_FILE = BASE_DIR / "terminology.json"
TERMINOLOGY_PRESETS_DIR = BASE_DIR / "presets"
TRANSLATION_CACHE_FILE = BASE_DIR / "translation_cache.json"

# ==================== 热键配置 ====================
HOTKEY = "ctrl+shift+t"               # 触发翻译的热键

# ==================== OCR 配置 ====================
OCR_USE_ANGLE_CLS = True
OCR_USE_GPU = True                    # 优先使用 GPU，不可用时自动回退 CPU

# ==================== 字幕检测配置 ====================
AUTO_DETECT_SUBTITLE_REGION = True    # 自动检测字幕区域
SUBTITLE_BOTTOM_RATIO = 0.40          # 屏幕底部 40% 视为字幕区

# ==================== 文本合并配置 ====================
MERGE_Y_THRESHOLD = 15                # 同一行 y 坐标差阈值（像素）
MERGE_X_GAP_THRESHOLD = 50           # 同一行 x 间距阈值（像素）

# ==================== 通用设置加载 ====================
def _load_settings():
    """集中从 app_settings.json 加载配置（运行时可被 UI 覆盖）"""
    try:
        from app_settings import load_settings
        s = load_settings()
        return (
            s.get("llm_api_key") or os.environ.get("LLM_API_KEY", ""),
            s.get("llm_api_url") or os.environ.get("LLM_API_URL", "https://api.openai.com/v1/chat/completions"),
            s.get("llm_model") or os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            s.get("subtitle_duration", 6),
            s.get("subtitle_font_size", 22),
            s.get("source_lang", "en"),
            s.get("target_lang", "zh"),
            s.get("save_debug_images", False)
        )
    except Exception:
        return (
            os.environ.get("LLM_API_KEY", ""),
            os.environ.get("LLM_API_URL", "https://api.openai.com/v1/chat/completions"),
            os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            6, 22, "en", "zh", False
        )

(LLM_API_KEY, LLM_API_URL, LLM_MODEL, 
 SUBTITLE_DURATION, SUBTITLE_FONT_SIZE, 
 SOURCE_LANG, TARGET_LANG, SAVE_DEBUG_IMAGES) = _load_settings()

OCR_LANG = SOURCE_LANG  # OCR 语言随源语言变动
LLM_TIMEOUT = 15                      # 请求超时（秒）

# ==================== 字幕显示配置 ====================
# SUBTITLE_DURATION, SUBTITLE_FONT_SIZE 已从 settings 加载
SUBTITLE_FONT_COLOR = "#FFD700"       # 金黄色
SUBTITLE_BG_COLOR = "rgba(0,0,0,180)" # 半透明黑色背景
SUBTITLE_PADDING = 8                  # 内边距（像素）

# ==================== 截图模式 ====================
class CaptureMode:
    WINDOW = "window"
    REGION = "region"
    FULLSCREEN = "fullscreen"
