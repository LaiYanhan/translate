"""
terminology_manager.py - 术语管理：读写 terminology.json + 可视化管理窗口
"""

import json
import logging
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QMessageBox, QHeaderView
)
from PyQt6.QtCore import Qt
from config import TERMINOLOGY_FILE

logger = logging.getLogger(__name__)


# ==================== 数据读写 ====================

def load_terminology() -> dict[str, str]:
    """加载术语表，返回 {英文: 中文} 字典"""
    path = Path(TERMINOLOGY_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"加载术语表失败: {e}")
        return {}


def save_terminology(terms: dict[str, str]) -> None:
    """保存术语表到文件"""
    path = Path(TERMINOLOGY_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(terms, f, ensure_ascii=False, indent=2)
        logger.info(f"术语表已保存：{len(terms)} 条")
    except Exception as e:
        logger.error(f"保存术语表失败: {e}")


# ==================== 术语管理窗口 ====================

class TerminologyManagerDialog(QDialog):
    """可视化术语管理对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("术语管理")
        self.setMinimumSize(500, 400)
        self._terms: dict[str, str] = load_terminology()
        self._setup_ui()
        self._populate_table()

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
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        title = QLabel("术语管理 Terminology Manager")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        # 表格
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["English", "中文"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        # 输入行
        input_layout = QHBoxLayout()
        self.en_input = QLineEdit()
        self.en_input.setPlaceholderText("English term")
        self.zh_input = QLineEdit()
        self.zh_input.setPlaceholderText("中文术语")
        add_btn = QPushButton("Add Term")
        add_btn.clicked.connect(self._add_term)
        input_layout.addWidget(self.en_input)
        input_layout.addWidget(self.zh_input)
        input_layout.addWidget(add_btn)
        layout.addLayout(input_layout)

        # 按钮行
        btn_layout = QHBoxLayout()
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("deleteBtn")
        del_btn.clicked.connect(self._delete_term)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self._save)
        btn_layout.addStretch()
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _populate_table(self):
        self.table.setRowCount(0)
        for en, zh in self._terms.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(en))
            self.table.setItem(row, 1, QTableWidgetItem(zh))

    def _add_term(self):
        en = self.en_input.text().strip()
        zh = self.zh_input.text().strip()
        if not en or not zh:
            QMessageBox.warning(self, "警告", "请填写英文和中文术语。")
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(en))
        self.table.setItem(row, 1, QTableWidgetItem(zh))
        self.en_input.clear()
        self.zh_input.clear()

    def _delete_term(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = self.table.currentRow()
        self.table.removeRow(row)

    def _save(self):
        terms = {}
        for row in range(self.table.rowCount()):
            en_item = self.table.item(row, 0)
            zh_item = self.table.item(row, 1)
            if en_item and zh_item:
                terms[en_item.text().strip()] = zh_item.text().strip()
        self._terms = terms
        save_terminology(terms)
        QMessageBox.information(self, "成功", f"已保存 {len(terms)} 条术语。")
