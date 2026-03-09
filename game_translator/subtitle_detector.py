"""
subtitle_detector.py - 自动检测游戏字幕区域
策略：对整屏 OCR 结果统计 y 坐标，寻找底部高密度文本区
"""

import numpy as np
from typing import Optional
from config import AUTO_DETECT_SUBTITLE_REGION, SUBTITLE_BOTTOM_RATIO
import logging

logger = logging.getLogger(__name__)


def detect_subtitle_region(
    ocr_results: list,
    screen_height: int,
    screen_width: int,
) -> Optional[dict]:
    """
    分析 OCR 结果，自动定位字幕区域（屏幕底部 40%）。

    :param ocr_results: [(text, box, conf), ...]
    :param screen_height: 屏幕高度（像素）
    :param screen_width: 屏幕宽度（像素）
    :return: {"top": y, "left": 0, "width": w, "height": h} 或 None
    """
    if not AUTO_DETECT_SUBTITLE_REGION or not ocr_results:
        return None

    # 计算底部阈值
    bottom_threshold = screen_height * (1.0 - SUBTITLE_BOTTOM_RATIO)

    # 筛选在底部区域的 box
    bottom_boxes = []
    for text, box, conf in ocr_results:
        ys = [p[1] for p in box]
        center_y = (min(ys) + max(ys)) / 2
        if center_y >= bottom_threshold:
            bottom_boxes.append(box)

    if not bottom_boxes:
        logger.debug("未检测到底部文本区域，回退全屏模式")
        return None

    # 计算包围框
    all_ys = [p[1] for box in bottom_boxes for p in box]
    all_xs = [p[0] for box in bottom_boxes for p in box]

    top_y = int(min(all_ys)) - 10   # 稍微扩展边距
    bot_y = int(max(all_ys)) + 10
    left_x = 0                       # 水平方向取全宽
    right_x = screen_width

    top_y = max(0, top_y)
    bot_y = min(screen_height, bot_y)

    region = {
        "top": top_y,
        "left": left_x,
        "width": right_x - left_x,
        "height": bot_y - top_y,
    }

    logger.info(f"检测到字幕区域: {region}")
    return region


def filter_subtitle_results(
    ocr_results: list,
    screen_height: int,
) -> list:
    """
    仅保留屏幕底部 40% 区域的 OCR 结果（用于纯过滤模式）。

    :param ocr_results: [(text, box, conf), ...]
    :param screen_height: 屏幕高度
    :return: 过滤后的结果
    """
    threshold = screen_height * (1.0 - SUBTITLE_BOTTOM_RATIO)
    filtered = []
    for item in ocr_results:
        text, box, conf = item
        ys = [p[1] for p in box]
        center_y = (min(ys) + max(ys)) / 2
        if center_y >= threshold:
            filtered.append(item)
    return filtered
