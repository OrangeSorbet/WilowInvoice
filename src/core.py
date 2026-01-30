import os
import re
import cv2
import numpy as np
import pandas as pd
import pytesseract
from pdf2image import convert_from_path
from datetime import datetime

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

POPPLER_PATH = r"C:\poppler-25.11.0\Library\bin"
OCR_CONFIG = r"--oem 3 --psm 6"

GST_REGEX = r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]"
AMOUNT_REGEX = r"\d+\.\d{2}"
IFSC_REGEX = r"[A-Z]{4}0[A-Z0-9]{6}"
ACCOUNT_REGEX = r"\b\d{9,18}\b"
AMOUNT_REGEX_COMMA = r"[\d,]+\.\d{2}"
DATE_REGEX = r"\d{1,2}[- ][A-Za-z]{3}[- ]\d{2}"

class InvoicePipeline:

    def process_invoice(self, pdf_path):
        raw_text = self._run_ocr(pdf_path)
        if not raw_text.strip():
            raise RuntimeError("OCR produced empty text")
        data = self._parse_text(raw_text)
        data["Filename"] = os.path.basename(pdf_path)
        data["Processed On"] = datetime.now().strftime("%d-%m-%Y %H:%M")
        return data

    def _run_ocr(self, pdf_path):
        text = ""
        images = convert_from_path(pdf_path, dpi=300, poppler_path=POPPLER_PATH)
        for img in images:
            img = np.array(img)
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            page_text = pytesseract.image_to_string(gray, config=OCR_CONFIG)
            text += page_text + "\n"
        return text

    def _parse_text(self, raw_text):
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
        if "Suyog Engineers" in raw_text:
            return self._parse_invoice_4(lines)
        elif "Intellivise" in raw_text or "BALANCE DUE" in raw_text:
            return self._parse_invoice_3(lines)
        else:
            return self._parse_invoice_2(lines, raw_text)

    def _parse_invoice_2(self, lines, raw_text):
        data = {}
        data["Vendor Name"] = "SUJIT ENGINEERING"

        for l in lines:
            if "GSTIN No." in l:
                m = re.search(GST_REGEX, l)
                if m:
                    data["Vendor GSTIN"] = m.group()
                break

        for i, l in enumerate(lines):
            if l.startswith("Party Details"):
                data["Invoice No"] = l.split("Invoice No. :")[-1].strip()
                if i + 1 < len(lines):
                    buyer_line = lines[i + 1]
                    data["Buyer Name"] = buyer_line.split("Dated")[0].strip()
                    if "Dated :" in buyer_line:
                        data["Invoice Date"] = buyer_line.split("Dated :")[-1].strip()
                if i + 4 < len(lines):
                    data["Buyer Address"] = " ".join(lines[i + 2:i + 5])
                break

        for l in lines:
            if "GSTIN NO :" in l:
                m = re.search(GST_REGEX, l)
                if m:
                    data["Buyer GSTIN"] = m.group()
            if "PO No :" in l:
                data["PO No"] = l.split("PO No :")[-1].strip()

        for l in lines:
            if "Place Supply" in l:
                data["Place of Supply"] = l.split(":")[-1].strip()
                break

        for l in lines:
            if "7308" in l and "KGS" in l:
                nums = re.findall(AMOUNT_REGEX, l)
                parts = re.findall(r"\b\d+\b|KGS", l)
                if len(parts) >= 3 and len(nums) >= 2:
                    data["HSN"] = parts[0]
                    data["Quantity"] = parts[1]
                    data["Unit"] = "KGS"
                    data["Rate"] = nums[0]
                    data["Item Amount"] = nums[1]
                break

        desc = []
        capture = False
        for l in lines:
            if "DRG NO" in l:
                capture = True
            if capture:
                if "Rs. In words" in l:
                    break
                desc.append(l)
        if desc:
            data["Item Description"] = " ".join(desc)

        cgst = sgst = None
        for l in lines:
            if "CGST" in l:
                m = re.search(AMOUNT_REGEX, l)
                if m:
                    cgst = float(m.group())
                    data["CGST Amount"] = f"{cgst:.2f}"
            elif l.startswith("it"):
                m = re.search(AMOUNT_REGEX, l)
                if m:
                    sgst = float(m.group())
                    data["SGST Amount"] = f"{sgst:.2f}"

        if "Item Amount" in data and cgst is not None and sgst is not None:
            amt = float(data["Item Amount"])
            data["Taxable Amount"] = f"{amt:.2f}"
            data["Grand Total"] = f"{amt + cgst + sgst:.2f}"

        for l in lines:
            if "Bank Name" in l:
                data["Bank Name"] = l.split(":")[-1].strip()
            elif "Branch :" in l:
                data["Branch"] = l.split(":")[-1].strip()
            elif "IFSC Code" in l:
                m = re.search(IFSC_REGEX, l)
                if m:
                    data["IFSC Code"] = m.group()
            elif "A/CNo" in l:
                m = re.search(ACCOUNT_REGEX, l)
                if m:
                    data["Account No"] = m.group()

        return data

    def _parse_invoice_3(self, lines):
        data = {
            "Vendor Name": "Intellivise Engineering Services Pvt Ltd",
            "Buyer Name": "Wilo Mather and Platt Pumps Pvt. Ltd."
        }

        for i, l in enumerate(lines):
            if "27AAHCI" in l:
                m = re.search(GST_REGEX, l)
                if m:
                    data["Vendor GSTIN"] = m.group()

            if "27AABCD" in l and not data.get("Buyer GSTIN"):
                m = re.search(GST_REGEX, l)
                if m:
                    data["Buyer GSTIN"] = m.group()

            if "INVOICE NO" in l:
                parts = l.split("#")
                if len(parts) > 1:
                    data["Invoice No"] = parts[-1].strip()

            if "INVOICE DATE" in l and i + 1 < len(lines):
                m = re.search(r"\d{2}/\d{2}/\d{4}", lines[i + 1])
                if m:
                    data["Invoice Date"] = m.group()

            if "PO No" in l:
                data["PO No"] = l.split(":")[-1].strip()

            if "BALANCE DUE" in l:
                m = re.search(AMOUNT_REGEX_COMMA, l)
                if m:
                    raw_amt = m.group().replace(",", "")
                    data["Grand Total"] = "{:,.2f}".format(float(raw_amt))

        items = []
        for l in lines:
            if re.search(r"\b\d{8}\b", l) and re.search(AMOUNT_REGEX_COMMA, l):
                item = {}
                hsn_m = re.search(r"(\b\d{8}\b)", l)
                if hsn_m:
                    item["HSN/SAC"] = hsn_m.group(1)
                    parts = l.split(item["HSN/SAC"])
                    if len(parts) > 1:
                        raw_desc = re.sub(r"^[\d\s|]+", "", parts[0]).strip()
                        item["Item Description"] = raw_desc
                        clean_right = re.sub(r"[€£¥ZzOo|)]", " ", parts[1])
                        nums = re.findall(r"[\d,]+\.?\d*", clean_right)
                        valid_nums = []
                        for n in nums:
                            try:
                                val = float(n.replace(",", ""))
                                if val > 0:
                                    valid_nums.append(val)
                            except:
                                pass
                        if len(valid_nums) >= 2:
                            item["Quantity"] = str(valid_nums[0])
                            item["Taxable Value"] = "{:,.2f}".format(valid_nums[1])
                        items.append(item)

        if items:
            data.update(items[0])

        return {k: v for k, v in data.items() if v and str(v).strip()}

    def _parse_invoice_4(self, lines):
        data = {
            "Vendor Name": "Suyog Engineers",
            "Buyer Name": "Wilo Mather & Platt Pumps Pvt.Ltd."
        }

        addr_lines = []
        capture_addr = False

        for i, l in enumerate(lines):
            if "Suyog Engineers" in l and "Bank" not in l:
                capture_addr = True
                continue
            if capture_addr:
                if "GSTIN" in l or "Reference" in l or len(addr_lines) > 3:
                    capture_addr = False
                else:
                    if any(x in l for x in ["Block", "MIDC", "Pune", "Maharashtra", "India"]):
                        addr_lines.append(re.split(r"\(A\d+", l)[0].strip(" |,"))

            if "AAUFS" in l:
                m = re.search(GST_REGEX, l)
                if m:
                    data["Vendor GSTIN"] = m.group()

            if "AABCD" in l:
                m = re.search(GST_REGEX, l)
                if m:
                    data["Buyer GSTIN"] = m.group()

            if "Invoice No" in l or "dt." in l:
                m = re.search(r"(?:A|No\.\s*)?(\d{3,4})\b", l)
                if m:
                    candidate = m.group(1)
                    if 100 < int(candidate) < 10000 and candidate != "2025":
                        data["Invoice No"] = candidate

            if "Ack Date" in l or "Dated" in l or "Jan" in l:
                m = re.search(DATE_REGEX, l)
                if m and not data.get("Invoice Date"):
                    data["Invoice Date"] = m.group()

            if "W.O.NO." in l:
                m = re.search(r"\d{8,10}", l)
                if m:
                    data["PO No"] = m.group()

            if "Motor Vehicle No" in l and i + 1 < len(lines):
                m = re.search(r"([A-Z0-9]{4,12})$", lines[i + 1])
                if m:
                    data["Vehicle No"] = m.group(1)

        if addr_lines:
            data["Vendor Address"] = ", ".join(addr_lines)

        for l in lines:
            if l.startswith("1 ") and "7308" in l:
                parts = re.split(r"\s+7308", l)
                if len(parts) > 1:
                    data["Item Description"] = parts[0].replace("1 ", "", 1).strip().replace("MOTOR'STOOL", "MOTOR STOOL")
                    data["HSN"] = "7308" + parts[1][:5]
                    qty_match = re.search(r"(\d+[:.]\d+)\s*NOS", parts[1])
                    if qty_match:
                        data["Quantity"] = qty_match.group(1).replace(":", ".")
                        data["Unit"] = "NOS"
                    amounts = re.findall(AMOUNT_REGEX_COMMA, parts[1])
                    if len(amounts) >= 2:
                        data["Rate"] = amounts[0]
                        data["Taxable Amount"] = amounts[-1]

            if "CGST" in l:
                m = re.search(AMOUNT_REGEX_COMMA, l)
                if m:
                    data["CGST Amount"] = m.group()

            if "SGST" in l:
                m = re.search(AMOUNT_REGEX_COMMA, l)
                if m:
                    data["SGST Amount"] = m.group()

            amounts = re.findall(AMOUNT_REGEX_COMMA, l)
            if len(amounts) >= 3 and not data.get("SGST Amount"):
                if abs(float(amounts[1].replace(",", "")) - float(amounts[2].replace(",", ""))) < 5:
                    data["SGST Amount"] = amounts[2]

            if "Total" in l and "Amount" in l:
                m = re.search(AMOUNT_REGEX_COMMA, l)
                if m:
                    data["Grand Total"] = m.group()

        try:
            taxable = float(data.get("Taxable Amount", "0").replace(",", ""))
            cgst = float(data.get("CGST Amount", "0").replace(",", ""))
            sgst = float(data.get("SGST Amount", "0").replace(",", ""))
            if not data.get("Grand Total") and taxable > 0:
                data["Grand Total"] = "{:,.2f}".format(taxable + cgst + sgst)
        except:
            pass

        return {k: v for k, v in data.items() if v and str(v).strip()}

def export_to_excel(rows, output_path):
    if not rows:
        raise RuntimeError("No data to export")
    base, ext = os.path.splitext(output_path)
    final = output_path
    i = 1
    while os.path.exists(final):
        final = f"{base}_{i}{ext}"
        i += 1
    pd.DataFrame(rows).to_excel(final, index=False)
    return final
