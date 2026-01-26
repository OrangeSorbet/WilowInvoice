import re
import cv2
import numpy as np
import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from datetime import datetime
import os
import pandas as pd

# ---------------- CONFIG ----------------
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\poppler-25.12.0\Library\bin"

OCR_CONFIG = r"--oem 3 --psm 6"

AMOUNT_REGEX = r"(\d{1,3}(?:,\d{3})*\.\d{2})"
GST_REGEX = r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]"
DATE_REGEX = r"\d{2}[/-]\d{2}[/-]\d{4}"
PAN_REGEX = r"[A-Z]{5}[0-9]{4}[A-Z]"
IFSC_REGEX = r"[A-Z]{4}0[A-Z0-9]{6}"
ACCOUNT_REGEX = r"\b\d{9,18}\b"


class InvoicePipeline:
    """
    Extracts maximum possible information from invoices
    and returns a flat dict ready for Excel export.
    """

    # ================= PUBLIC =================
    def process_invoice(self, pdf_path):
        filename = os.path.basename(pdf_path)

        raw_text, method = self._extract_text(pdf_path)
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

        # ---- FIX SGST RATE (table OCR issue) ----
        cgst_rate = self._find_percent(lines, "CGST")
        sgst_rate = self._find_percent(lines, "SGST")
        if not sgst_rate and cgst_rate:
            sgst_rate = cgst_rate

        return {
            # -------- File / Status --------
            "Filename": filename,
            "Status": "PROCESSED",
            "Processed On": datetime.now().strftime("%d-%m-%Y %H:%M"),
            "OCR Method": method,

            # -------- Invoice Header --------
            "Invoice Type": self._find_contains(lines, ["TAX INVOICE"]),
            "Invoice No": self._label_value(raw_text, ["Invoice No"]),
            "Invoice Date": self._first_match(DATE_REGEX, raw_text),
            "Due Date": self._label_value(raw_text, ["Due Date"]),
            "Place of Supply": self._label_value(raw_text, ["Place of Supply"]),
            "Currency": "INR",

            # -------- Vendor --------
            "Vendor Name": self._vendor_name(lines),
            "Vendor Address": self._vendor_address(lines),
            "Vendor GSTIN": self._first_match(GST_REGEX, raw_text),
            "Vendor PAN": self._first_match(PAN_REGEX, raw_text),
            "Vendor Email": self._label_value(raw_text, ["Email"]),

            # -------- Buyer --------
            "Buyer Name": self._buyer_name(lines),
            "Buyer Address": self._buyer_address(lines),
            "Buyer GSTIN": self._buyer_gstin(lines),

            # -------- Line Items --------
            **self._extract_items(lines),

            # -------- Taxes --------
            "CGST Rate (%)": cgst_rate,
            "CGST Amount": self._find_amount(lines, "CGST"),
            "SGST Rate (%)": sgst_rate,
            "SGST Amount": self._find_amount(lines, "SGST"),
            "Total Tax": self._find_amount(lines, "Tax"),

            # -------- Totals --------
            "Subtotal": self._find_amount(lines, "Sub Total"),
            "Grand Total": self._find_amount(lines, "Grand Total"),
            "Amount in Words": self._label_value(raw_text, ["Amount in Words"]),

            # -------- Bank --------
            "Bank Name": self._label_value(raw_text, ["Bank"]),
            "Account Name": self._label_value(raw_text, ["Account Name"]),
            "Account Number": self._first_match(ACCOUNT_REGEX, raw_text),
            "IFSC Code": self._first_match(IFSC_REGEX, raw_text),
            "Branch": self._label_value(raw_text, ["Branch"]),

            # -------- Raw Backup --------
            "Raw OCR Text": raw_text
        }

    # ================= EXTRACTION =================
    def _extract_text(self, path):
        text = ""
        method = "TEXT"

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        if len(text.strip()) < 50:
            method = "OCR"
            images = convert_from_path(path, dpi=300, poppler_path=POPPLER_PATH)
            for img in images:
                text += self._ocr(img) + "\n"

        return self._normalize(text), method

    def _ocr(self, img):
        img = np.array(img)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        gray = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 2
        )
        return pytesseract.image_to_string(gray, config=OCR_CONFIG)

    def _normalize(self, text):
        return (
            text.replace("₹", "INR ")
                .replace("Rs.", "INR ")
                .replace("Rs", "INR ")
                .replace("â‚¹", "INR ")
        )

    # ================= ITEMS =================
    def _extract_items(self, lines):
        sr, desc, hsn, qty, rate, amt = [], [], [], [], [], []

        for l in lines:
            if re.search(r"\d+\s+.*\d{2}\.\d{2}$", l):
                numbers = re.findall(AMOUNT_REGEX, l)
                if numbers:
                    amt.append(numbers[-1].replace(",", ""))
                    rate.append(numbers[-1].replace(",", ""))
                desc.append(l)
                sr.append(str(len(sr) + 1))
                qty.append("1")
                hsn.append("")

        return {
            "Item Sr Nos": "|".join(sr),
            "Item Descriptions": "|".join(desc),
            "HSN/SAC Codes": "|".join(hsn),
            "Quantities": "|".join(qty),
            "Rates": "|".join(rate),
            "Item Amounts": "|".join(amt)
        }

    # ================= HELPERS =================
    def _find_amount(self, lines, keyword):
        for l in lines:
            if keyword.lower() in l.lower():
                m = re.findall(AMOUNT_REGEX, l)
                if m:
                    return m[-1].replace(",", "")
        return ""

    def _find_percent(self, lines, keyword):
        for l in lines:
            if keyword.lower() in l.lower() and "%" in l:
                m = re.search(r"(\d+)%", l)
                if m:
                    return m.group(1)
        return ""

    def _label_value(self, text, labels):
        for label in labels:
            m = re.search(rf"{label}\s*[:\-]?\s*(.+)", text, re.I)
            if m:
                return m.group(1).split("\n")[0].strip()
        return ""

    def _first_match(self, regex, text):
        m = re.search(regex, text)
        return m.group() if m else ""

    def _find_contains(self, lines, keys):
        for l in lines:
            for k in keys:
                if k in l.upper():
                    return k
        return ""

    def _vendor_name(self, lines):
        for l in lines:
            if any(x in l.upper() for x in ["PVT", "LTD", "PRIVATE"]):
                return l
        return ""

    def _vendor_address(self, lines):
        return " ".join(lines[1:6])

    def _buyer_name(self, lines):
        for i, l in enumerate(lines):
            if any(x in l.lower() for x in ["invoice to", "bill to"]):
                return lines[i + 1]
        return ""

    def _buyer_address(self, lines):
        for i, l in enumerate(lines):
            if any(x in l.lower() for x in ["invoice to", "bill to"]):
                return " ".join(lines[i + 2:i + 6])
        return ""

    def _buyer_gstin(self, lines):
        for l in lines:
            if re.search(GST_REGEX, l):
                return l
        return ""


# ================= EXCEL EXPORT =================
def export_to_excel(rows, output_path):
    """
    rows: list of dicts returned by InvoicePipeline.process_invoice()
    """

    if not rows:
        raise ValueError("No data to export")

    df = pd.DataFrame(rows)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Invoices")

        ws = writer.sheets["Invoices"]

        for i, col in enumerate(df.columns, 1):
            max_len = max(
                df[col].astype(str).map(len).max(),
                len(col)
            )
            col_letter = chr(64 + i) if i <= 26 else None
            if col_letter:
                ws.column_dimensions[col_letter].width = min(max_len + 2, 60)
