import sys
import os
from PySide6.QtWidgets import QApplication
from src.ui import MainWindow
from src.utils import setup_logger

def main():
    # 1. Initialize Logging
    setup_logger()
    
    # 2. Create the Qt Application
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Clean, consistent look across OS

    # 3. Launch UI
    window = MainWindow()
    window.show()

    # 4. Execute Event Loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()