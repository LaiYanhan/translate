"""
ocr_engine.py - OCR 引擎封装
使用 PaddleOCR，优先 GPU，回退 CPU
"""

import logging
import numpy as np
from paddleocr import PaddleOCR
from config import OCR_LANG, OCR_USE_ANGLE_CLS, OCR_USE_GPU

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
        return cls._instance

    def initialize(self):
        """初始化 PaddleOCR，检测 GPU 可用性"""
        if self._initialized:
            return

        use_gpu = OCR_USE_GPU and _detect_gpu()
        mode_label = "GPU" if use_gpu else "CPU"
        logger.info(f"OCR Mode: {mode_label}")
        print(f"[OCR] OCR Mode: {mode_label}")

        import paddle
        import inspect
        
        ocr_kwargs = {
            "use_angle_cls": OCR_USE_ANGLE_CLS,
            "lang": OCR_LANG,
            "use_gpu": use_gpu,
            "show_log": False,
        }
        
        # Determine how to pass parameters based on what PaddleOCR version accepts
        while True:
            try:
                self.ocr = PaddleOCR(**ocr_kwargs)
                break
            except ValueError as e:
                err_str = str(e)
                if "Unknown argument:" in err_str:
                    bad_arg = err_str.split("Unknown argument:")[-1].strip()
                    logger.debug(f"PaddleOCR 不再支持参数: {bad_arg}")
                    
                    if bad_arg in ocr_kwargs:
                        ocr_kwargs.pop(bad_arg)
                        # 如果是在报错 use_gpu，则尝试加 device=gpu
                        if bad_arg == "use_gpu":
                            if hasattr(paddle, "device") and hasattr(paddle.device, "set_device"):
                                paddle.device.set_device("gpu" if use_gpu else "cpu")
                            # 新版本可能使用 device 参数
                            ocr_kwargs["device"] = "gpu" if use_gpu else "cpu"
                    else:
                        raise
                else:
                    raise
        
        self._initialized = True

    def recognize(self, image: np.ndarray) -> list[tuple[str, list, float]]:
        """
        对图像执行 OCR 识别
        :param image: BGR numpy 数组
        :return: [(text, box, confidence), ...]
                 box 为 4 个点的坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        """
        if not self._initialized:
            self.initialize()

        if image is None or getattr(image, 'size', 0) == 0:
            logger.warning("传入的图像为空，跳过 OCR。")
            return []

        try:
            # Handle standard PaddleOCR 2.x and some 3.x
            try:
                result = self.ocr.ocr(image, cls=OCR_USE_ANGLE_CLS)
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
