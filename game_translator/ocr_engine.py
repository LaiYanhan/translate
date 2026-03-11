import os
import sys
import logging
import numpy as np
from pathlib import Path
import config
# ==================== 打包环境兼容性补丁 ====================
# 强制跳过 PaddleX 的动态依赖检查 (该检查在 EXE 环境下经常误报)
try:
    import paddlex.utils.deps as pdx_deps
    # 定义一个永远返回 True 的函数，骗过自检系统
    def _mock_require_extra(*args, **kwargs):
        return True
    pdx_deps.require_extra = _mock_require_extra
except ImportError:
    pass

# ==================== 路径 & 环境变量配置 ====================
# 将模型存储在程序目录下的 ocr_models 文件夹，而非 C 盘用户目录
BASE_DIR = Path(__file__).parent
MODELS_DIR = str(BASE_DIR / "ocr_models")
os.environ["PADDLE_HOME"] = MODELS_DIR
os.environ["PADDLE_PDX_PADDLE_HOME"] = MODELS_DIR # 针对 PaddleX 3.x

logger = logging.getLogger(__name__)
# ==================== GPU 检测 ====================

def _detect_gpu() -> bool:
    """检测是否有可用 GPU（通过 paddle）"""
    try:
        import paddle
        return paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
    except Exception:
        return False


# ==================== OCR 引擎单例 ====================

class OCREngine:
    """PaddleOCR 封装，单例模式，仅初始化一次"""

    _instance: "OCREngine | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._current_lang = ""
            from paddleocr import PaddleOCR
            cls._instance.PaddleOCR = PaddleOCR
        return cls._instance

    def initialize(self):
        """初始化 PaddleOCR，检测 GPU 可用性"""
        if self._initialized and self._current_lang == config.OCR_LANG:
            return

        use_gpu = config.OCR_USE_GPU and _detect_gpu()
        mode_label = "GPU" if use_gpu else "CPU"
        logger.info(f"OCR Mode: {mode_label}, Language: {config.OCR_LANG}")
        print(f"[OCR] OCR Mode: {mode_label}, Language: {config.OCR_LANG}")

        import paddle
        import inspect
        
        ocr_kwargs = {
            "use_angle_cls": config.OCR_USE_ANGLE_CLS,
            "lang": config.OCR_LANG,
            "use_gpu": use_gpu,
            "show_log": False,
        }
        
        # Determine how to pass parameters based on what PaddleOCR version accepts
        while True:
            try:
                self.ocr = self.PaddleOCR(**ocr_kwargs)
                break
            except (ValueError, RuntimeError) as e:
                err_str = str(e)
                logger.warning(f"PaddleOCR 初始化尝试失败: {err_str}")
                
                if "No valid PaddlePaddle model found" in err_str:
                    # 针对 PaddleOCR 3.x 的特定错误：可能是该语言的高级模型未下载或下载错误
                    # 尝试降级：取消某些可能导致路径错误的参数，或者提示用户
                    if ocr_kwargs.get("use_angle_cls"):
                        logger.info("尝试关闭 use_angle_cls 以进入精简模式...")
                        ocr_kwargs["use_angle_cls"] = False
                        continue
                    if ocr_kwargs.get("use_gpu"):
                        logger.info("尝试回退至 CPU 模式...")
                        ocr_kwargs["use_gpu"] = False
                        use_gpu = False
                        if "device" in ocr_kwargs: ocr_kwargs["device"] = "cpu"
                        continue
                    # 如果都试过了还没用，那可能是模型文件损坏，抛出给用户看
                    raise RuntimeError(
                        f"无法载入 OCR 模型 ({config.OCR_LANG})。\n"
                        "原因：{err_str}\n"
                        "建议：删除 C:\\Users\\你的用户名\\.paddleocr 文件夹后重试，强制程序重新下载模型。"
                    ) from e

                if "Unknown argument:" in err_str:
                    bad_arg = err_str.split("Unknown argument:")[-1].strip()
                    logger.debug(f"PaddleOCR 不再支持参数: {bad_arg}")
                    
                    if bad_arg in ocr_kwargs:
                        ocr_kwargs.pop(bad_arg)
                        # 如果是在报错 use_gpu，则尝试加 device=gpu
                        if bad_arg == "use_gpu":
                            if hasattr(paddle, "device") and hasattr(paddle.device, "set_device"):
                                paddle.device.set_device("gpu" if use_gpu else "cpu")
                            ocr_kwargs["device"] = "gpu" if use_gpu else "cpu"
                        continue
                    else:
                        raise
                else:
                    raise
        
        
        self._current_lang = config.OCR_LANG
        self._initialized = True

    def recognize(self, image: np.ndarray) -> list[tuple[str, list, float]]:
        """
        对图像执行 OCR 识别
        :param image: BGR numpy 数组
        :return: [(text, box, confidence), ...]
                 box 为 4 个点的坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        """
        if not self._initialized or self._current_lang != config.OCR_LANG:
            self.initialize()

        if image is None or getattr(image, 'size', 0) == 0:
            logger.warning("传入的图像为空，跳过 OCR。")
            return []

        try:
            # Handle standard PaddleOCR 2.x and some 3.x
            try:
                result = self.ocr.ocr(image, cls=config.OCR_USE_ANGLE_CLS)
            except AttributeError:
                # PaddleOCR 3.4+ PaddleX Pipeline uses predict()
                result = list(self.ocr.predict(image))
            except TypeError as e:
                # "unexpected keyword argument 'cls'"
                if "unexpected keyword argument" in str(e):
                    if hasattr(self.ocr, "ocr"):
                        result = self.ocr.ocr(image)
                    else:
                        result = list(self.ocr.predict(image))
                else:
                    raise

            output = []
            
            # Extract standard PaddleOCR format result
            # v2/v3: result is typically a list of lists.
            # PaddleX pipeline v3.5: predict() yields dicts.
            if hasattr(result, "__iter__") and not isinstance(result, str):
                for res in result:
                    if not res:
                        continue
                    
                    # PaddleX format (OCRResult object behaving like a dict)
                    if hasattr(res, "keys") or isinstance(res, dict):
                        try:
                            # PaddleX normally uses "rec_texts", "rec_scores" and "dt_polys"
                            texts = res["rec_texts"] if "rec_texts" in res else res.get("rec_text", [])
                            scores = res["rec_scores"] if "rec_scores" in res else res.get("rec_score", [])
                            boxes = res.get("dt_polys", [])
                            
                            if len(texts) == len(boxes):
                                for box, text, score in zip(boxes, texts, scores):
                                    if hasattr(box, "tolist"):
                                        box = box.tolist()
                                    output.append((text, box, score))
                                continue
                        except Exception as e:
                            logger.debug(f"PaddleX 格式提取跳过: {e}")
                    
                    # Classic list format
                    elif isinstance(res, list):
                        # typically `result` is [ [[box1], (txt1, conf1)], [[box2], ...] ]
                        # Handle classic nested structure
                        for line in res:
                            if isinstance(line, (list, tuple)) and len(line) == 2:
                                box, text_conf = line
                                if isinstance(text_conf, (list, tuple)) and len(text_conf) == 2:
                                    text, conf = text_conf
                                    output.append((text, box, conf))

            return output
        except Exception as e:
            logger.error(f"OCR 识别失败: {e}")
            return []


# 全局单例
ocr_engine = OCREngine()
