"""
ocr_postprocess.py - OCR 文本后处理：合并同行碎片文本
"""

import numpy as np
from typing import List, Tuple
from config import MERGE_Y_THRESHOLD, MERGE_X_GAP_THRESHOLD


# box 格式: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] (顺时针，左上为起点)

def _box_center_y(box) -> float:
    """返回 bounding box 中心 y 坐标"""
    ys = [p[1] for p in box]
    return (min(ys) + max(ys)) / 2


def _box_left_x(box) -> float:
    """返回 bounding box 最左边 x 坐标"""
    return min(p[0] for p in box)


def _box_right_x(box) -> float:
    """返回 bounding box 最右边 x 坐标"""
    return max(p[0] for p in box)


def _box_top_y(box) -> float:
    return min(p[1] for p in box)


def _box_bottom_y(box) -> float:
    return max(p[1] for p in box)


def _merge_boxes(boxes) -> list:
    """将多个 box 合并为一个包围 box（矩形）"""
    xs = [p[0] for box in boxes for p in box]
    ys = [p[1] for box in boxes for p in box]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _clean_text(text: str) -> str:
    """清理 OCR 常见误识别，特别是行首的 I 被识别成 / 或 |"""
    if not text:
        return text
    
    # 1. 处理行首误识别
    # 如果以 / 或 | 开头，且后面是空格或大写字母，极大概率是 "I"
    # 例如: "/ was" -> "I was", "| am" -> "I am"
    if text.startswith(("/", "|")):
        if len(text) == 1:
            return "I"
        if text[1] == " " or text[1].isupper():
            text = "I" + text[1:]
            
    # 2. 处理带括号的行首误识别
    # 例如: "(/ am" -> "(I am", "(| was" -> "(I was"
    if text.startswith(("( /", "( |", "(/", "(|")):
        # 寻找斜杠或竖线的索引
        idx = text.find("/")
        if idx == -1:
            idx = text.find("|")
            
        if idx != -1 and idx < 3: # 确保在开头附近
            if len(text) > idx + 1:
                if text[idx+1] == " " or text[idx+1].isupper():
                    text = text[:idx] + "I" + text[idx+1:]
                    
    return text


def merge_ocr_lines(
    ocr_results: List[Tuple[str, list, float]]
) -> List[Tuple[str, list, float]]:
    """
    合并 OCR 识别到的同行碎片文本。

    :param ocr_results: [(text, box, confidence), ...]
    :return: 合并后的 [(merged_text, merged_box, avg_confidence), ...]
    """
    if not ocr_results:
        return []

    # 按 y 坐标排序（从上到下）
    sorted_items = sorted(ocr_results, key=lambda x: _box_center_y(x[1]))

    lines: List[List[Tuple[str, list, float]]] = []   # 每条"行"包含若干 item
    current_line: List[Tuple[str, list, float]] = [sorted_items[0]]

    for item in sorted_items[1:]:
        text, box, conf = item
        prev_y = _box_center_y(current_line[-1][1])
        curr_y = _box_center_y(box)

        if abs(curr_y - prev_y) <= MERGE_Y_THRESHOLD:
            # 同一行
            current_line.append(item)
        else:
            lines.append(current_line)
            current_line = [item]
    lines.append(current_line)

    merged: List[Tuple[str, list, float]] = []

    for line in lines:
        # 按 x 坐标从左到右排序
        line.sort(key=lambda x: _box_left_x(x[1]))

        # 再次合并：相邻 x 间距小于阈值的合并为一句
        groups: List[List[Tuple[str, list, float]]] = [[line[0]]]

        for item in line[1:]:
            prev_right = _box_right_x(groups[-1][-1][1])
            curr_left = _box_left_x(item[1])
            gap = curr_left - prev_right

            if gap <= MERGE_X_GAP_THRESHOLD:
                groups[-1].append(item)
            else:
                groups.append([item])

        for group in groups:
            texts = [g[0] for g in group]
            boxes = [g[1] for g in group]
            confs = [g[2] for g in group]

            merged_text = " ".join(texts)
            # 应用后处理清理
            merged_text = _clean_text(merged_text)
            
            merged_box = _merge_boxes(boxes)
            avg_conf = float(np.mean(confs))
            merged.append((merged_text, merged_box, avg_conf))

    # --- 最终补充：垂直合并断句 ---
    return _merge_vertical_sentences(merged)


def _merge_vertical_sentences(
    merged_items: List[Tuple[str, list, float]]
) -> List[Tuple[str, list, float]]:
    """
    如果第一行结尾没有标点，且第二行在垂直下方不远处，则合并为一句。
    """
    if len(merged_items) < 2:
        return merged_items

    final_results = []
    i = 0
    while i < len(merged_items):
        item = merged_items[i]
        
        # 如果是最后一条，直接加入
        if i == len(merged_items) - 1:
            final_results.append(item)
            break
            
        next_item = merged_items[i+1]
        
        text, box, conf = item
        n_text, n_box, n_conf = next_item
        
        # 判定准则 1：当前行结尾是否缺少结束标点
        # 英文常见结束标点：., !, ?, ", )
        ends_with_punc = text.rstrip().endswith((".", "!", "?", "\"", ")", "。", "！", "？", "”", "）"))
        
        # 判定准则 2：垂直距离是否接近
        h1 = _box_bottom_y(box) - _box_top_y(box)
        v_gap = _box_top_y(n_box) - _box_bottom_y(box)
        
        # 判定准则 3：水平对齐（左侧对齐程度）
        left_gap = abs(_box_left_x(box) - _box_left_x(n_box))
        
        # 判定准则 4：语义启发式（防止合并人名/标签）
        # 如果第一行很短（如 "YU"），且第二行以大写字母开头，通常是两个独立句/项
        is_short_label = len(text.strip()) < 10 or len(text.strip().split()) <= 2
        starts_new_sentence = n_text.strip() and n_text.strip()[0].isupper()
        is_likely_name = text.strip().isupper() and len(text.strip()) < 15

        # 经验阈值：垂直间距小于 1.5 倍行高，且左侧对齐度较好
        is_close = v_gap < h1 * 1.5 and left_gap < h1 * 2
        
        # 排除规则：如果是短标签/人名且下一句又是开头，则不合并
        should_avoid_merge = (is_short_label and starts_new_sentence) or is_likely_name

        if not ends_with_punc and is_close and not should_avoid_merge:
            # 执行合并
            new_text = text + " " + n_text
            new_box = _merge_boxes([box, n_box])
            new_conf = (conf + n_conf) / 2
            merged_items[i+1] = (new_text, new_box, new_conf) # 更新下一条
        else:
            final_results.append(item)
            
        i += 1
        
    return final_results
