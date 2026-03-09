"""
terminology_manager.py - 术语管理：读写 terminology.json + 可视化管理窗口
"""

import json
import logging
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QMessageBox, QHeaderView, QInputDialog, QApplication,
    QPlainTextEdit
)
from PyQt6.QtCore import Qt
from config import TERMINOLOGY_FILE

logger = logging.getLogger(__name__)


# ==================== 数据读写 ====================

def load_terminology() -> tuple[dict[str, dict], str]:
    """
    加载术语表，返回 (terms_dict, background_info) 元组
    terms_dict 格式: {英文: {"translation": 中文, "context": 语境}}
    """
    path = Path(TERMINOLOGY_FILE)
    default_res = ({}, "")
    if not path.exists():
        return default_res
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default_res
        
        # 判断是新格式还是旧格式
        if "terms" in data and isinstance(data["terms"], dict):
            # 新格式: {"background_info": "...", "terms": {...}}
            raw_terms = data["terms"]
            bg_info = data.get("background_info", "")
        else:
            # 旧格式: 直接就是术语字典
            raw_terms = data
            bg_info = ""

        # 转换术语为统一格式
        terms_result = {}
        for k, v in raw_terms.items():
            if isinstance(v, str):
                terms_result[k] = {"translation": v, "context": ""}
            elif isinstance(v, dict):
                terms_result[k] = {
                    "translation": v.get("translation", ""),
                    "context": v.get("context", "")
                }
        return terms_result, bg_info
    except Exception as e:
        logger.error(f"加载术语表失败: {e}")
        return default_res

def save_terminology(terms: dict[str, dict], background_info: str = "") -> None:
    """保存术语表和背景信息到文件"""
    path = Path(TERMINOLOGY_FILE)
    data = {
        "background_info": background_info,
        "terms": terms
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"术语表已保存：{len(terms)} 条，背景信息长度：{len(background_info)}")
    except Exception as e:
        logger.error(f"保存术语表失败: {e}")


# ==================== 术语管理窗口 ====================

class TerminologyManagerDialog(QDialog):
    """可视化术语管理对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("术语管理")
        self.setMinimumSize(700, 600)
        self._terms, self._background_info = load_terminology()
        self._setup_ui()
        self._populate_table()
        self.bg_info_edit.setPlainText(self._background_info)

    def _setup_ui(self):
        self.setStyleSheet("""
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QTableWidget { background: #181825; color: #cdd6f4;
                           gridline-color: #313244; border: 1px solid #313244; }
            QTableWidget::item:selected { background: #45475a; }
            QHeaderView::section { background: #313244; color: #cba6f7;
                                   padding: 4px; border: none; }
            QLineEdit { background: #313244; color: #cdd6f4;
                        border: 1px solid #585b70; padding: 4px; border-radius: 4px; }
            QPushButton { background: #7f849c; color: #1e1e2e; border: none;
                          padding: 6px 12px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background: #cba6f7; }
            QPushButton#deleteBtn { background: #f38ba8; }
            QPushButton#deleteBtn:hover { background: #eba0ac; }
            QPushButton#saveBtn { background: #a6e3a1; }
            QPushButton#saveBtn:hover { background: #94e2d5; }
            QPlainTextEdit { background: #181825; color: #cdd6f4;
                             border: 1px solid #313244; border-radius: 4px; padding: 4px; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        title = QLabel("术语管理 Terminology Manager")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        # 背景信息区域
        bg_label = QLabel("🌍 游戏背景设定 / 全局翻译建议 (给 AI 的额外提示)：")
        bg_label.setStyleSheet("color: #89b4fa; font-weight: bold; margin-top: 5px;")
        layout.addWidget(bg_label)
        self.bg_info_edit = QPlainTextEdit()
        self.bg_info_edit.setPlaceholderText("在此输入游戏的背景信息、角色关系、专有语气要求等...\n例如：'这是一个关于魔法学院的故事，主角名 Kanan 翻译成果南，语气要活泼。'")
        self.bg_info_edit.setMaximumHeight(100)
        layout.addWidget(self.bg_info_edit)

        # 表格标题
        table_label = QLabel("📜 核心术语表：")
        table_label.setStyleSheet("color: #cba6f7; font-weight: bold; margin-top: 5px;")
        layout.addWidget(table_label)

        # 表格
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["English", "中文", "设定/语境 (可选)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        # 输入行
        input_layout = QHBoxLayout()
        self.en_input = QLineEdit()
        self.en_input.setPlaceholderText("English term")
        self.zh_input = QLineEdit()
        self.zh_input.setPlaceholderText("中文术语")
        self.ctx_input = QLineEdit()
        self.ctx_input.setPlaceholderText("特定角色/场景限制")
        add_btn = QPushButton("Add Term")
        add_btn.clicked.connect(self._add_term)
        input_layout.addWidget(self.en_input)
        input_layout.addWidget(self.zh_input)
        input_layout.addWidget(self.ctx_input)
        input_layout.addWidget(add_btn)
        layout.addLayout(input_layout)

        # 按钮行
        btn_layout = QHBoxLayout()
        
        extract_btn = QPushButton("AI Auto Extract ✨")
        extract_btn.setStyleSheet("background: #89b4fa; color: #1e1e2e; font-weight: bold;")
        extract_btn.clicked.connect(self._auto_extract)
        
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("deleteBtn")
        del_btn.clicked.connect(self._delete_term)
        
        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self._save)
        
        btn_layout.addWidget(extract_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _populate_table(self):
        self.table.setRowCount(0)
        for en, data in self._terms.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(en))
            self.table.setItem(row, 1, QTableWidgetItem(data["translation"]))
            self.table.setItem(row, 2, QTableWidgetItem(data["context"]))

    def _add_term(self):
        en = self.en_input.text().strip()
        zh = self.zh_input.text().strip()
        ctx = self.ctx_input.text().strip()
        if not en or not zh:
            QMessageBox.warning(self, "警告", "请至少填写英文和中文术语。")
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(en))
        self.table.setItem(row, 1, QTableWidgetItem(zh))
        self.table.setItem(row, 2, QTableWidgetItem(ctx))
        self.en_input.clear()
        self.zh_input.clear()
        self.ctx_input.clear()

    def _delete_term(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = self.table.currentRow()
        self.table.removeRow(row)

    def _auto_extract(self):
        text, ok = QInputDialog.getMultiLineText(
            self, "AI 自动提取术语", "请粘贴一大段相关的英文游戏文本或维基介绍：\n(AI将自动为您分析并提取特定设定的角色名词和专有术语)"
        )
        if ok and text.strip():
            import translator
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.setWindowTitle("术语管理 - ✨ AI 正在努力分析提取中，请稍候...")
            QApplication.processEvents()
            
            try:
                new_terms = translator.extract_terms_from_text(text.strip())
            except Exception as e:
                new_terms = {}
                logger.error(f"UI调用AI提取失败: {e}")
                
            QApplication.restoreOverrideCursor()
            self.setWindowTitle("术语管理")
            
            if new_terms:
                added = 0
                for en, data in new_terms.items():
                    if en not in self._terms:
                        self._terms[en] = data
                        added += 1
                if added > 0:
                    self._populate_table()
                    QMessageBox.information(
                        self, "提取成功", 
                        f"AI 成功提取了 {len(new_terms)} 个术语！\n其中 {added} 个新术语已自动添加到列表。\n\n请检查无误后点击 Save 保存。"
                    )
                else:
                    QMessageBox.information(self, "提示", "AI 提取到了术语，但它们均已存在于列表中。")
            else:
                QMessageBox.warning(self, "失败", "提取失败或没有提取到任何术语。请确保 API 配置正确或文本足够长。")

    def _save(self):
        terms = {}
        for row in range(self.table.rowCount()):
            en_item = self.table.item(row, 0)
            zh_item = self.table.item(row, 1)
            ctx_item = self.table.item(row, 2)
            if en_item and zh_item:
                ctx_text = ctx_item.text().strip() if ctx_item else ""
                terms[en_item.text().strip()] = {
                    "translation": zh_item.text().strip(),
                    "context": ctx_text
                }
        self._terms = terms
        self._background_info = self.bg_info_edit.toPlainText().strip()
        save_terminology(terms, self._background_info)
        QMessageBox.information(self, "成功", f"已保存 {len(terms)} 条术语及背景信息。")
