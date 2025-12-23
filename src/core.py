import os
import re
import cv2
import pdfplumber
import pytesseract
import numpy as np
import spacy
from pdf2image import convert_from_path
from PIL import Image

# Explicitly set Tesseract path if needed (Common Windows Path)
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class InvoicePipeline:
    def __init__(self):
        # Load NLP model (lightweight English)
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except:
            self.nlp = None # Fallback if model missing

    def process_invoice(self, file_path):
        """Orchestrator: Ingest -> Extract -> Parse -> Validate"""
        text = self._extract_text(file_path)
        if not text:
            return {"error": "No text extracted"}
            
        data = self._parse_data(text)
        data['validation_passed'] = self._validate_math(data)
        return data

    def _extract_text(self, path):
        """Hybrid Strategy: Try Digital first, fallback to OCR"""
        text = ""
        # 1. Try Digital Extraction (Fast, Accurate)
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # 2. If empty/scant, assume Scanned -> OCR
        if len(text) < 50:
            print("  -> Scanned PDF detected. Running OCR...")
            images = convert_from_path(path)
            for img in images:
                # Pre-processing for better OCR accuracy
                cv_img = np.array(img)
                gray = cv2.cvtColor(cv_img, cv2.COLOR_RGB2GRAY)
                # Binarize
                _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
                text += pytesseract.image_to_string(thresh) + "\n"
        
        return text

    def _parse_data(self, text):
        """Extracts fields using Regex & NLP"""
        data = {
            "vendor": "Unknown",
            "invoice_no": None,
            "date": None,
            "total": 0.0,
            "items": []
        }

        # --- NER for Vendor (Organization) ---
        if self.nlp:
            doc = self.nlp(text)
            for ent in doc.ents:
                if ent.label_ == "ORG":
                    data['vendor'] = ent.text
                    break # Assume first ORG is vendor (simplistic but effective)

        # --- Regex Heuristics ---
        # Invoice Number (Look for patterns like INV-123 or #123)
        inv_match = re.search(r'(?i)(invoice\s*no|inv\.?|#)\s*[:.]?\s*([a-zA-Z0-9-]+)', text)
        if inv_match:
            data['invoice_no'] = inv_match.group(2)

        # Date (dd/mm/yyyy or yyyy-mm-dd)
        date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})', text)
        if date_match:
            data['date'] = date_match.group(0)

        # Total Amount (Look for largest float near "Total")
        # Finds 1,234.56 or 1234.56
        prices = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2})', text)
        if prices:
            # Clean commas and convert to float
            floats = [float(p.replace(',', '')) for p in prices]
            data['total'] = max(floats) # Heuristic: Grand total is usually the largest number

        return data

    def _validate_math(self, data):
        # Placeholder: Real system would sum line items and compare
        return data['total'] > 0