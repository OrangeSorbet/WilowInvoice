import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QFileDialog, QTableWidget, 
                               QTableWidgetItem, QLabel, QHeaderView, QProgressBar)
from PySide6.QtCore import Qt, QThread, Signal
from .core import InvoicePipeline
from .storage import StorageEngine
from .security import SecurityManager
from .utils import setup_logger

logger = setup_logger()

class Worker(QThread):
    """Background Thread for Processing (Prevent UI Freeze)"""
    progress = Signal(str, str, str) # Filename, Status, Vendor
    finished = Signal()

    def __init__(self, file_paths):
        super().__init__()
        self.files = file_paths
        self.pipeline = InvoicePipeline()
        self.storage = StorageEngine()

    def run(self):
        for path in self.files:
            try:
                fname = os.path.basename(path)
                # 1. Security Check
                fhash = SecurityManager.get_file_hash(path)
                
                # 2. Extract
                data = self.pipeline.process_invoice(path)
                
                # 3. Save
                saved = self.storage.save_invoice(fname, fhash, data)
                status = "Success" if saved else "Duplicate"
                
                self.progress.emit(fname, status, str(data.get('vendor')))
            except Exception as e:
                logger.error(f"Failed {path}: {e}")
                self.progress.emit(os.path.basename(path), "Error", "N/A")
        
        self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wilow Invoice Extractor [Enterprise]")
        self.resize(900, 600)
        
        # Components
        self.btn_upload = QPushButton("📂 Upload Invoices")
        self.btn_export = QPushButton("💾 Export CSV")
        self.table = QTableWidget()
        self.status_bar = QProgressBar()
        
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        main_widget = QWidget()
        layout = QVBoxLayout()
        
        # Top Bar
        top_layout = QHBoxLayout()
        top_layout.addWidget(self.btn_upload)
        top_layout.addWidget(self.btn_export)
        layout.addLayout(top_layout)

        # Table Config
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Filename", "Vendor", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        # Bottom Bar
        layout.addWidget(self.status_bar)
        self.status_bar.setValue(0)
        
        main_widget.setLayout(layout)
        self.setCentralWidget(main_widget)
        
        # Styles
        self.setStyleSheet("""
            QMainWindow { background-color: #f0f0f0; }
            QPushButton { padding: 10px; background-color: #0078d7; color: white; border: none; }
            QPushButton:hover { background-color: #005a9e; }
            QTableWidget { border: 1px solid #ccc; background-color: white; }
        """)

    def _connect_signals(self):
        self.btn_upload.clicked.connect(self.upload_files)
        self.btn_export.clicked.connect(self.export_data)

    def upload_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select Invoices", "", "PDF Files (*.pdf)")
        if files:
            self.status_bar.setRange(0, 0) # Indeterminate loading
            self.worker = Worker(files)
            self.worker.progress.connect(self.update_table)
            self.worker.finished.connect(lambda: self.status_bar.setRange(0, 100))
            self.worker.start()

    def update_table(self, fname, status, vendor):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(fname))
        self.table.setItem(row, 1, QTableWidgetItem(vendor))
        self.table.setItem(row, 2, QTableWidgetItem(status))

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Data", "export.csv", "CSV (*.csv)")
        if path:
            count = StorageEngine().export_to_csv(path)
            self.status_bar.setFormat(f"Exported {count} rows")