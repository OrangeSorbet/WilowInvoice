import os
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

import easyocr
from pdf2image import convert_from_path
import numpy as np
import cv2
import json
from scipy.cluster.hierarchy import fclusterdata
import tkinter as tk
from tkinter import filedialog
import re

POPPLER_PATH = r"C:\poppler-25.12.0\Library\bin"

reader = easyocr.Reader(['en'], gpu=False)

# -----------------------------
# 1️⃣ Helper regex & NLP utilities
# -----------------------------
def find_value(lines, keys):
    for line in lines:
        for key in keys:
            if key.lower() in line.lower():
                return line
    return ""

def extract_regex(text, pattern):
    match = re.search(pattern, text)
    if not match:
        return ""
    # if there is at least one capturing group, return group 1
    if match.lastindex:
        return match.group(1)
    # else return the whole match
    return match.group(0)


# -----------------------------
# 2️⃣ Line-item table normalizer
# -----------------------------
def normalize_line_items(tables):
    items = []

    for table in tables:
        header = " ".join(table[0]).lower() if table else ""
        if any(k in header for k in ["description", "hsn", "qty", "amount"]):
            for row in table[1:]:
                row_text = " ".join(row)
                items.append({
                    "item_code": extract_regex(row_text, r"\b\d{6,}\b"),
                    "description": row_text,
                    "hsn": extract_regex(row_text, r"\b\d{6,8}\b"),
                    "qty": extract_regex(row_text, r"\b\d+(\.\d+)?\b"),
                    "unit": "NOS" if "nos" in row_text.lower() else "",
                    "rate": "",
                    "amount": extract_regex(row_text, r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b")
                })
    return items

# -----------------------------
# 3️⃣ Universal invoice formatter (dynamic version)
# -----------------------------
def format_invoice(ocr_json):
    """
    Dynamically formats invoice JSON extracted from OCR.
    Works for any invoice structure, preserves all information.
    """
    pages = ocr_json.get("pages", [])
    if not pages:
        return {}

    # Flatten all text lines from text_blocks and tables
    all_lines = []
    all_text = ""
    for page in pages:
        for line in page.get("text_blocks", []):
            all_lines.append(line.strip())
            all_text += line + " "
        for table in page.get("tables", []):
            for row in table:
                row_text = " ".join(cell.strip() for cell in row)
                all_lines.append(row_text)
                all_text += row_text + " "

    all_text = all_text.strip()

    # Helper functions
    def find_line(keywords):
        for line in all_lines:
            if any(k.lower() in line.lower() for k in keywords):
                return line
        return ""

    def regex_search(pattern, text=all_text, fallback=""):
        match = re.search(pattern, text)
        if match:
            # return group 1 if exists, else full match
            return match.group(1) if match.lastindex else match.group(0)
        return fallback

    # Supplier & Buyer
    supplier_line = find_line(["PVT", "LTD", "ENGINEERS", "COMPANY", "PRIVATE"])
    buyer_line = find_line(["Buyer", "MATHER", "WILO", "CUSTOMER", "Client"])

    supplier_gstin = regex_search(r"\b[0-9A-Z]{15}\b")
    buyer_gstin = regex_search(r"\b[0-9A-Z]{15}\b")

    # Invoice Meta
    invoice_no = regex_search(r"(?i)(?:Invoice No\.?|INV[:\s])\s*([\w/-]+)")
    invoice_date = regex_search(r"\b\d{2}[-/]\d{2}[-/]\d{4}\b")
    po_no = regex_search(r"(?i)(?:PO No\.?|Order[:\s])\s*([\w/-]+)")
    place_of_supply = find_line(["Place of Supply"]) or "Unknown"

    # Line items (from tables)
    line_items = []
    for page in pages:
        for table in page.get("tables", []):
            header_row = table[0] if table else []
            if any(k.lower() in " ".join(header_row).lower() for k in ["description", "hsn", "qty", "amount"]):
                for row in table[1:]:
                    row_text = " ".join(row)
                    line_items.append({
                        "description": row_text,
                        "hsn": regex_search(r"\b\d{4,8}\b", row_text),
                        "qty": regex_search(r"\b\d+(\.\d+)?\b", row_text),
                        "unit": "NOS" if "nos" in row_text.lower() else "",
                        "rate": regex_search(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b", row_text),
                        "amount": regex_search(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b", row_text)
                    })

    # Taxes
    cgst = find_line(["CGST"]) or regex_search(r"CGST[:\s]?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)")
    sgst = find_line(["SGST"]) or regex_search(r"SGST[:\s]?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)")
    igst = find_line(["IGST"]) or regex_search(r"IGST[:\s]?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)")

    # Totals
    taxable_value = regex_search(r"Taxable Amt[:\s]?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", all_text)
    total_tax = regex_search(r"Total Tax[:\s]?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", all_text)
    grand_total = regex_search(r"Grand Total[:\s]?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", all_text)
    amount_in_words = find_line(["Rupees", "Only"]) or ""

    # Bank details
    bank_name = find_line(["Bank"])
    account_no = regex_search(r"\b\d{9,18}\b", all_text)
    ifsc = regex_search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", all_text)

    # Declarations: all lines not captured
    captured_lines = {supplier_line, buyer_line, cgst, sgst, igst, taxable_value, total_tax, grand_total, amount_in_words, bank_name, account_no, ifsc}
    declarations = [line for line in all_lines if line not in captured_lines and line.strip()]

    formatted = {
        "supplier": {
            "name": supplier_line,
            "gstin": supplier_gstin,
            "contact": "",  # can extend to extract phone/email
        },
        "buyer": {
            "name": buyer_line,
            "gstin": buyer_gstin,
            "address": "",  # can extend to detect buyer address
        },
        "invoice_meta": {
            "invoice_no": invoice_no,
            "invoice_date": invoice_date,
            "po_no": po_no,
            "place_of_supply": place_of_supply
        },
        "line_items": line_items,
        "taxes": {
            "cgst": cgst,
            "sgst": sgst,
            "igst": igst
        },
        "totals": {
            "taxable_value": taxable_value,
            "total_tax": total_tax,
            "grand_total": grand_total,
            "amount_in_words": amount_in_words
        },
        "bank_details": {
            "bank_name": bank_name,
            "account_no": account_no,
            "ifsc": ifsc
        },
        "declarations": declarations
    }

    return formatted

# -----------------------------
# 4️⃣ OCR & PDF utilities
# -----------------------------
def preprocess(img):
    h, w = img.shape[:2]
    max_side = max(h, w)
    if max_side > 4000:
        scale = 4000 / max_side
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
    return img

def select_pdfs():
    root = tk.Tk()
    root.withdraw()
    file_paths = filedialog.askopenfilenames(
        title="Select Invoice PDFs",
        filetypes=[("PDF files", "*.pdf")]
    )
    return list(file_paths)

def ocr_page(img):
    results = reader.readtext(img, detail=1, paragraph=False)
    words = []
    for box, text, conf in results:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        words.append({
            "text": text,
            "conf": float(conf),
            "x": int(min(xs)),
            "y": int(min(ys)),
            "w": int(max(xs) - min(xs)),
            "h": int(max(ys) - min(ys))
        })
    return words

def cluster_rows(words, threshold=25):
    points = np.array([[w["y"]] for w in words])
    labels = fclusterdata(points, threshold, criterion="distance")
    rows = {}
    for label, word in zip(labels, words):
        rows.setdefault(label, []).append(word)
    return [sorted(row, key=lambda w: w["x"]) for row in rows.values()]

def detect_tables(rows, min_cols=3):
    tables = []
    current = []
    for row in rows:
        if len(row) >= min_cols:
            current.append(row)
        else:
            if current:
                tables.append(current)
                current = []
    if current:
        tables.append(current)
    return tables

def table_to_json(table):
    return [[cell["text"] for cell in row] for row in table]

def pdf_to_json(pdf_path):
    images = convert_from_path(pdf_path, dpi=300, poppler_path=POPPLER_PATH)
    output = {"file": os.path.basename(pdf_path), "pages": []}

    for page_no, pil_img in enumerate(images, 1):
        img = preprocess(np.array(pil_img))
        words = ocr_page(img)
        rows = cluster_rows(words)
        tables = detect_tables(rows)

        page = {"page": page_no, "tables": [], "text_blocks": []}
        used_words = set()

        for table in tables:
            table_json = table_to_json(table)
            page["tables"].append(table_json)
            for row in table:
                for cell in row:
                    used_words.add(id(cell))

        # remaining text
        for row in rows:
            line = " ".join(w["text"] for w in row if id(w) not in used_words)
            if line.strip():
                page["text_blocks"].append(line)

        output["pages"].append(page)

    return output

# -----------------------------
# 5️⃣ Main processing
# -----------------------------
pdf_files = select_pdfs()
all_data = []

for pdf in pdf_files:
    print(f"Processing: {pdf}")
    raw_json = pdf_to_json(pdf)

    # format invoice immediately
    formatted_invoice = format_invoice(raw_json)

    # save both raw and formatted
    raw_name = os.path.splitext(os.path.basename(pdf))[0] + "_raw.json"
    formatted_name = os.path.splitext(os.path.basename(pdf))[0] + "_formatted.json"

    with open(raw_name, "w", encoding="utf-8") as f:
        json.dump(raw_json, f, indent=2, ensure_ascii=False)

    with open(formatted_name, "w", encoding="utf-8") as f:
        json.dump(formatted_invoice, f, indent=2, ensure_ascii=False)

    all_data.append(formatted_invoice)

# save all formatted invoices together
with open("invoice_structured.json", "w", encoding="utf-8") as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False)

print("All files processed and saved.")
