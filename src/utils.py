import logging
import os
import sys
from logging.handlers import RotatingFileHandler

def setup_logger(name="WilowApp", log_file="app.log"):
    # Ensure logs dir exists
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Rotate logs: Max 5MB, keep 3 backups
    handler = RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=3)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Console output for dev
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(handler)
        logger.addHandler(console)

    return logger

def get_safe_path(filename):
    # Prevents directory traversal attacks
    return os.path.basename(filename)