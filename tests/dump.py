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

POPPLER_PATH = r"C:\poppler-25.12.0\Library\bin"

reader = easyocr.Reader(['en'], gpu=False)

def preprocess(img):
    # img is RGB
    h, w = img.shape[:2]
    max_side = max(h, w)

    if max_side > 4000:
        scale = 4000 / max_side
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
    return img


def select_pdfs():
    root = tk.Tk()
    root.withdraw()  # hide main window

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

    # sort rows top → bottom
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
    table_json = []
    for row in table:
        table_json.append([cell["text"] for cell in row])
    return table_json

def pdf_to_json(pdf_path):
    images = convert_from_path(pdf_path, dpi=300, poppler_path=POPPLER_PATH)

    output = {
        "file": os.path.basename(pdf_path),
        "pages": []
    }

    for page_no, pil_img in enumerate(images, 1):
        img = preprocess(np.array(pil_img))
        words = ocr_page(img)

        rows = cluster_rows(words)
        tables = detect_tables(rows)

        page = {
            "page": page_no,
            "tables": [],
            "text_blocks": []
        }

        used_words = set()

        for table in tables:
            table_json = table_to_json(table)
            page["tables"].append(table_json)
            for row in table:
                for cell in row:
                    used_words.add(id(cell))

        # remaining text (headers, totals, addresses)
        for row in rows:
            line = " ".join(w["text"] for w in row if id(w) not in used_words)
            if line.strip():
                page["text_blocks"].append(line)

        output["pages"].append(page)

    return output


pdf_files = select_pdfs()

all_data = []

for pdf in pdf_files:
    print(f"Processing: {pdf}")
    result = pdf_to_json(pdf)

    # save per-file JSON
    out_name = os.path.splitext(os.path.basename(pdf))[0] + ".json"
    with open(out_name, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    all_data.append(result)

print("All files processed.")


with open("invoice_structured.json", "w", encoding="utf-8") as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False)

print("Saved invoice_structured.json")