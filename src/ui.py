import os
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTableWidget,
    QTableWidgetItem, QLabel, QHeaderView, QProgressBar,
    QFrame, QGraphicsDropShadowEffect, QAbstractItemView
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPropertyAnimation, QPoint, QEasingCurve
from PySide6.QtGui import QColor

from src.core import InvoiceEngine, export_to_json
from .security import SecurityManager
from .utils import setup_logger

logger = setup_logger()

# ---------------- ASSETS ----------------

class AssetManager:
    @staticmethod
    def load_stylesheet():
        path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'styles.qss')
        path = os.path.abspath(path)
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read()
        return ""

# ---------------- UI COMPONENTS ----------------

class StatusBadge(QLabel):
    def __init__(self, text, status_type):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        colors = {
            "Processed": ("#dcfce7", "#166534"),
            "Duplicate": ("#ffedd5", "#9a3412"),
            "Error":     ("#fee2e2", "#991b1b")
        }
        bg, text_col = colors.get(status_type, ("#e2e8f0", "#475569"))
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {text_col};
                border-radius: 10px;
                padding: 4px 12px;
                font-weight: 700;
                font-size: 11px;
            }}
        """)

class Toast(QLabel):
    def __init__(self, parent, message, level="info", duration=3000):
        super().__init__(parent)
        self.setText(message)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        color_map = {
            "info": "#3b82f6",
            "success": "#22c55e",
            "warning": "#f59e0b",
            "error": "#ef4444"
        }
        bg_color = color_map.get(level, "#333")

        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: white;
                padding: 12px 16px;
                border-radius: 6px;
                font-weight: 500;
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setYOffset(4)
        self.setGraphicsEffect(shadow)

        self.adjustSize()
        self.setFixedWidth(min(400, parent.width() - 40))
        self._animate(duration)

    def _animate(self, duration):
        parent = self.parent()
        margin = 24
        x_pos = parent.width() - self.width() - margin
        start_y = parent.height()
        end_y = parent.height() - self.height() - margin

        self.move(x_pos, start_y)
        self.show()

        self.anim = QPropertyAnimation(self, b"pos")
        self.anim.setDuration(300)
        self.anim.setStartValue(QPoint(x_pos, start_y))
        self.anim.setEndValue(QPoint(x_pos, end_y))
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.start()

        QTimer.singleShot(duration, lambda: (self.close(), self.deleteLater()))

# ---------------- WORKER ----------------

class Worker(QThread):
    progress = Signal(dict, str)
    finished = Signal()

    def __init__(self, files):
        super().__init__()
        self.files = files
        # Explicitly point to the .exe inside your custom path
        tesseract_exe = r"C:\Users\ashvi\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
        self.engine = InvoiceEngine(tesseract_cmd=tesseract_exe)

    def run(self):
        try:
            result = self.engine.process_batch(self.files)
            
            for inv in result.get("invoices", []):
                self.progress.emit(inv, "Processed")
                
            for err in result.get("errors", []):
                self.progress.emit(
                    {"Filename": err.get("file"), "Vendor Name": "N/A"}, 
                    "Error"
                )
        except Exception as e:
            logger.error(f"Worker thread failed: {e}")
        finally:
            self.finished.emit()

# ---------------- MAIN WINDOW ----------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wilow Invoice Extractor")
        self.resize(1100, 750)

        self.extracted_rows = []

        style_content = AssetManager.load_stylesheet()
        if style_content:
            self.setStyleSheet(style_content)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(32, 32, 32, 32)
        main_layout.setSpacing(24)

        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)

        title_block = QWidget()
        tb = QVBoxLayout(title_block)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(4)

        lbl_title = QLabel("Invoice Extraction")
        lbl_title.setObjectName("HeaderTitle")
        lbl_sub = QLabel("Secure offline processing pipeline • v1.0")
        lbl_sub.setObjectName("HeaderSubtitle")
        tb.addWidget(lbl_title)
        tb.addWidget(lbl_sub)

        self.btn_export = QPushButton("Export JSON")
        self.btn_export.setProperty("class", "outline")
        self.btn_export.setEnabled(False)
        self.btn_export.setFixedWidth(120)

        self.btn_upload = QPushButton("Upload Invoices")
        self.btn_upload.setProperty("class", "primary")
        self.btn_upload.setFixedWidth(160)

        h_layout.addWidget(title_block)
        h_layout.addStretch()
        h_layout.addWidget(self.btn_export)
        h_layout.addWidget(self.btn_upload)
        main_layout.addWidget(header)

        # Card
        self.card = QFrame()
        self.card.setObjectName("ContentCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 15))
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 24, 24, 24)

        lbl_card = QLabel("Processed Queue")
        lbl_card.setObjectName("CardTitle")
        card_layout.addWidget(lbl_card)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Filename", "Vendor Identified", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)

        card_layout.addWidget(self.table)
        main_layout.addWidget(self.card)

        # Footer
        footer = QWidget()
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(0, 0, 0, 0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        self.lbl_status = QLabel("System Ready")
        self.lbl_status.setFixedHeight(28)
        self.lbl_status.setObjectName("StatusPill")
        self.update_status_pill("System Ready", "idle")

        main_layout.addWidget(self.progress_bar)
        f_layout.addWidget(self.lbl_status)
        f_layout.addStretch()
        main_layout.addWidget(footer)

    def _connect_signals(self):
        self.btn_upload.clicked.connect(self.upload_files)
        self.btn_export.clicked.connect(self.export_data)

    def show_toast(self, message, level="info"):
        Toast(self, message, level)

    def update_status_pill(self, message, state="idle"):
        self.lbl_status.setText(message)
        styles = {
            "idle": "background-color: transparent; color: #64748b;",
            "working": "background-color: #e0f2fe; color: #0284c7; border: 1px solid #bae6fd;",
            "success": "background-color: #dcfce7; color: #166534; border: 1px solid #bbf7d0;",
            "error": "background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca;"
        }
        base = "padding: 0 16px; border-radius: 14px; font-weight: 600; font-size: 12px;"
        self.lbl_status.setStyleSheet(f"QLabel {{ {base} {styles.get(state)} }}")

    # ---------------- ACTIONS ----------------

    def upload_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Invoice PDFs", "", "PDF Files (*.pdf)"
        )
        if not files:
            return

        self.extracted_rows.clear()
        self.table.setRowCount(0)

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.update_status_pill("Processing invoices...", "working")
        self.btn_upload.setEnabled(False)
        self.btn_export.setEnabled(False)

        self.worker = Worker(files)
        self.worker.progress.connect(self.handle_progress)
        self.worker.finished.connect(self.handle_finished)
        self.worker.start()

    def handle_progress(self, data, status):
        row = self.table.rowCount()
        self.table.insertRow(row)

        fname = data.get("Filename", "Unknown")
        vendor = data.get("Vendor Name", "Unknown")

        self.table.setItem(row, 0, QTableWidgetItem(fname))
        self.table.setItem(row, 1, QTableWidgetItem(vendor))
        self.table.setCellWidget(row, 2, StatusBadge(status, status))

        self.extracted_rows.append(data)
        self.table.scrollToBottom()

    def handle_finished(self):
        self.progress_bar.setVisible(False)
        self.update_status_pill("Processing complete", "success")
        self.btn_upload.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.show_toast("Batch processing finished.", "success")

    def export_data(self):
        if not self.extracted_rows:
            self.show_toast("No data to export.", "warning")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON", "invoices_export.json", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            from src.core import export_to_json
            export_to_json(self.extracted_rows, path)
            self.show_toast("JSON exported successfully.", "success")
        except Exception as e:
            logger.error(f"Export failed: {e}")
            self.show_toast("Failed to export JSON.", "error")
