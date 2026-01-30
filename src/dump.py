import pytesseract
import cv2
import numpy as np
from pdf2image import convert_from_path

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\poppler-25.11.0\Library\bin"

images = convert_from_path(
    "Four Sample Supplier Invoices-3.pdf",
    dpi=300,
    poppler_path=POPPLER_PATH
)

for i, img in enumerate(images, 1):
    img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    text = pytesseract.image_to_string(
        img,
        config="--oem 3 --psm 6"
    )

    print("\n" + "="*40)
    print(f"PAGE {i} RAW OCR TEXT")
    print("="*40)
    print(text)
