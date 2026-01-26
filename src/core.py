import os
import re
import json
import uuid
import logging
import platform
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import json
from collections import defaultdict
from statistics import mean
import pdfplumber
import pytesseract
from PIL import Image

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BlockClassifier:
    """
    Deterministic, rule-based block classifier.
    NO extraction. NO math. NO guessing.
    """

    KEYWORDS = {
        "BANK": [
            "BANK", "IFSC", "A/C", "ACCOUNT", "BRANCH"
        ],
        "DECLARATION": [
            "DECLARE", "CERTIFIED", "WE HEREBY", "SUBJECT TO",
            "JURISDICTION", "AUTHORISED SIGNATORY"
        ],
        "ITEM_TABLE": [
            "SR", "QTY", "NOS", "RATE", "AMOUNT", "HSN", "ITEM"
        ],
        "TOTALS": [
            "TOTAL", "CGST", "SGST", "IGST", "TAXABLE", "GRAND"
        ],
        "INVOICE_META": [
            "INVOICE", "DATE", "PO NO", "ORDER NO", "CHALLAN"
        ]
    }

    def classify(self, block: dict) -> Tuple[str, float]:
        text = block["text"].upper()

        # ---------- HARD RULES FIRST ----------

        if self._contains_any(text, self.KEYWORDS["DECLARATION"]):
            return "DECLARATION", 0.95

        if self._contains_any(text, self.KEYWORDS["BANK"]):
            return "BANK", 0.95

        if self._looks_like_item_table(block):
            return "ITEM_TABLE", 0.9

        if self._contains_any(text, self.KEYWORDS["TOTALS"]):
            return "TOTALS", 0.9

        if self._contains_any(text, self.KEYWORDS["INVOICE_META"]):
            return "INVOICE_META", 0.85

        # ---------- POSITIONAL HEURISTICS ----------

        if block["top"] < 200:
            if "GST" in text or "ENGINEERING" in text:
                return "VENDOR", 0.7

        if "BILL TO" in text or "BUYER" in text:
            return "BUYER", 0.8

        return "UNKNOWN", 0.3

    # ----------------------------------------

    def _contains_any(self, text: str, keywords: list) -> bool:
        return any(k in text for k in keywords)

    def _looks_like_item_table(self, block: dict) -> bool:
        """
        Detects dense numeric + aligned text blocks
        """
        lines = block.get("lines", [])
        if len(lines) < 3:
            return False

        numeric_lines = 0
        for l in lines:
            if re.search(r"\d+\.\d{2}", l["text"]):
                numeric_lines += 1

        return numeric_lines >= 2

class LayoutBlockExtractor:
    """
    Responsible ONLY for converting pdfplumber words -> layout blocks
    No business logic. No invoice logic. No NLP.
    """

    def __init__(self,
                 y_tolerance: float = 6.0,
                 x_gap_tolerance: float = 25.0,
                 min_words: int = 2):
        self.y_tol = y_tolerance
        self.x_gap = x_gap_tolerance
        self.min_words = min_words

    def extract_blocks(self, page) -> list:
        """
        page: pdfplumber page
        returns: list of raw layout blocks
        """
        words = page.extract_words(use_text_flow=True)
        if not words:
            return []

        # 1️⃣ Group words into horizontal lines (Y-axis clustering)
        lines = self._cluster_words_to_lines(words)

        # 2️⃣ Merge nearby lines into BLOCKS
        blocks = self._merge_lines_to_blocks(lines)

        return blocks

    # -------------------------------------------------

    def _cluster_words_to_lines(self, words: list) -> list:
        """Group words with similar 'top' into visual lines"""
        words_sorted = sorted(words, key=lambda w: w['top'])
        lines = []
        current = []
        current_y = None

        for w in words_sorted:
            if current_y is None or abs(w['top'] - current_y) <= self.y_tol:
                current.append(w)
                current_y = mean([x['top'] for x in current])
            else:
                lines.append(self._finalize_line(current))
                current = [w]
                current_y = w['top']

        if current:
            lines.append(self._finalize_line(current))

        return lines

    def _finalize_line(self, words: list) -> dict:
        words_sorted = sorted(words, key=lambda w: w['x0'])
        text = " ".join(w['text'] for w in words_sorted)
        return {
            "text": text,
            "x0": min(w['x0'] for w in words_sorted),
            "x1": max(w['x1'] for w in words_sorted),
            "top": min(w['top'] for w in words_sorted),
            "bottom": max(w['bottom'] for w in words_sorted),
            "words": words_sorted
        }

    # -------------------------------------------------

    def _merge_lines_to_blocks(self, lines: list) -> list:
        """Merge vertically adjacent lines into layout blocks"""
        blocks = []
        current = None
        block_id = 1

        for line in lines:
            if current is None:
                current = self._new_block(block_id, line)
                continue

            vertical_gap = line['top'] - current['bottom']
            x_overlap = min(current['x1'], line['x1']) - max(current['x0'], line['x0'])

            if vertical_gap <= self.y_tol * 2 and x_overlap >= 0:
                # merge
                current['text'] += "\n" + line['text']
                current['x0'] = min(current['x0'], line['x0'])
                current['x1'] = max(current['x1'], line['x1'])
                current['bottom'] = max(current['bottom'], line['bottom'])
                current['lines'].append(line)
            else:
                if len(current['lines']) >= self.min_words:
                    blocks.append(current)
                block_id += 1
                current = self._new_block(block_id, line)

        if current and len(current['lines']) >= self.min_words:
            blocks.append(current)

        return blocks

    def _new_block(self, block_id: int, line: dict) -> dict:
        return {
            "block_id": block_id,
            "text": line['text'],
            "x0": line['x0'],
            "x1": line['x1'],
            "top": line['top'],
            "bottom": line['bottom'],
            "lines": [line],
            "block_type": None,
            "confidence": None
        }
    
def export_to_json(rows, output_path):
    """Saves the extracted invoice data to a JSON file."""
    if not rows:
        raise ValueError("No data to export")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, indent=4)
        
class InvoiceEngine:
    """
    Core engine for processing invoice PDFs.
    Optimized for Windows Desktop (Offline) usage.
    Removes heavy dependencies (cv2, pdf2image) in favor of PIL + pdfplumber.
    """

    # Compiled Regex Patterns (From your snippet + Standard)
    PATTERNS = {
        "amount": re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{2})"),
        "gstin": re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b"),
        "date": re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b"),
        "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
        "ifsc": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
        "account": re.compile(r"\b\d{9,18}\b"),
        "invoice_no": re.compile(r"(?i)(?:inv\.?|invoice)\s*(?:no\.?|num(?:ber)?|#)?\s*[:.\-]?\s*([a-zA-Z0-9/\-]+)"),
        "percentage": re.compile(r"(\d+(?:\.\d+)?)%"),
    }

    def __init__(self, tesseract_cmd: Optional[str] = None):
        """
        :param tesseract_cmd: Path to tesseract.exe.
        """
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        else:
            # Default Windows fallback
            default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.exists(default_path):
                pytesseract.pytesseract.tesseract_cmd = default_path

        # Tesseract Config
        self.ocr_config = r"--oem 3 --psm 6"

    def _extract_items_from_blocks(
        self,
        lines: List[str],
        layout_blocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Block-aware item extraction.
        Priority:
        1. ITEM_TABLE blocks
        2. OCR fallback with HARD filters
        """

        # ---------- CASE 1: BLOCKS EXIST ----------
        item_blocks = [
            b for b in layout_blocks
            if b.get("block_type") == "ITEM_TABLE"
            and b.get("confidence", 0) >= 0.8
        ]

        if item_blocks:
            collected_lines = []
            for b in item_blocks:
                for l in b.get("lines", []):
                    collected_lines.append(l["text"])

            return self._extract_items_heuristic(collected_lines)

        # ---------- CASE 2: OCR FALLBACK ----------
        safe_lines = []
        for line in lines:
            u = line.upper()

            # HARD REJECT junk
            if any(x in u for x in [
                "BANK", "IFSC", "ACCOUNT", "A/C",
                "DECLARATION", "WE HEREBY", "CERTIFIED",
                "SUBJECT TO", "JURISDICTION",
                "CGST", "SGST", "IGST", "GRAND TOTAL"
            ]):
                continue

            safe_lines.append(line)

        return self._extract_items_heuristic(safe_lines)

    def _extract_financials_from_blocks(
        self,
        lines: List[str],
        layout_blocks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Block-aware totals & GST extraction.
        Returns: total_before_tax, total_after_tax, cgst, sgst
        """

        # ---------- 1. Look for TOTALS/SUMMARY blocks ----------
        total_blocks = [
            b for b in layout_blocks
            if b.get("block_type") in ("TOTALS", "SUMMARY")
            and b.get("confidence", 0) >= 0.8
        ]

        candidate_lines = []
        if total_blocks:
            for b in total_blocks:
                for l in b.get("lines", []):
                    candidate_lines.append(l["text"])
        else:
            # ---------- 2. OCR fallback ----------
            for line in lines:
                u = line.upper()
                # Only allow likely totals lines
                if any(x in u for x in ["TOTAL", "AMOUNT", "CGST", "SGST", "IGST", "GST", "TAX"]):
                    # Reject junk
                    if not any(x in u for x in ["BANK", "ACCOUNT", "IFSC", "DECLARATION", "ISO", "SIGNATORY"]):
                        candidate_lines.append(line)

        # ---------------- EXTRACT VALUES ----------------
        # total_before_tax
        taxable_str = self._find_value(candidate_lines, "Taxable", self.PATTERNS["amount"])
        total_before_tax = self._parse_amount(taxable_str) if taxable_str else None

        # CGST / SGST
        def _validated_gst(keyword: str):
            rate_str = self._find_value(candidate_lines, keyword, self.PATTERNS["percentage"])
            amt_str = self._find_value(candidate_lines, keyword, self.PATTERNS["amount"])
            if not rate_str or not amt_str or not total_before_tax:
                return {"rate": None, "amount": None}
            rate = float(rate_str)
            amount = self._parse_amount(amt_str)
            expected = round(total_before_tax * rate / 100, 2)
            if abs(expected - amount) <= 2:
                return {"rate": rate, "amount": amount}
            return {"rate": None, "amount": None}

        cgst = _validated_gst("CGST")
        sgst = _validated_gst("SGST")

        # total_after_tax
        grand_total_str = self._find_value(candidate_lines, "Grand Total", self.PATTERNS["amount"])
        total_after_tax = self._parse_amount(grand_total_str) if grand_total_str else None

        return {
            "total_before_tax": total_before_tax,
            "total_after_tax": total_after_tax,
            "cgst": cgst,
            "sgst": sgst
        }

    def process_batch(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        Processes each page of each PDF as a separate invoice.
        Phase 1: Extract layout BLOCKS + existing heuristic extraction.
        """

        batch_id = str(uuid.uuid4())
        scan_time = datetime.now().isoformat()

        invoices = []
        errors = []

        extractor = LayoutBlockExtractor()

        for file_path in file_paths:
            if not os.path.exists(file_path):
                errors.append({"file": file_path, "error": "File not found"})
                continue

            try:
                with pdfplumber.open(file_path) as pdf:
                    for page_index, page in enumerate(pdf.pages):

                        # ---------- TEXT / OCR ----------
                        page_text = page.extract_text() or ""
                        ocr_triggered = False

                        if len(page_text.strip()) < 50:
                            ocr_triggered = True
                            page_text = self._perform_ocr(page)

                        lines = [
                            l.strip()
                            for l in page_text.split("\n")
                            if l.strip()
                        ]

                        # ---------- PHASE 1: BLOCK EXTRACTION ----------
                        try:
                            layout_blocks = extractor.extract_blocks(page)
                        except Exception as e:
                            logger.warning(f"Block extraction failed: {e}")
                            layout_blocks = []

                        # ---------- BLOCK CLASSIFICATION ----------
                        classifier = BlockClassifier()
                        for b in layout_blocks:
                            block_type, confidence = classifier.classify(b)
                            b["block_type"] = block_type
                            b["confidence"] = confidence

                        # ---------- EXISTING EXTRACTION (UNCHANGED) ----------
                        invoice_data = self._extract_invoice_data(
                            lines,
                            page_text,
                            os.path.basename(file_path),
                            batch_id,
                            scan_time,
                            layout_blocks
                        )

                        # ---------- ATTACH BLOCKS ----------
                        invoice_data["layout_blocks"] = layout_blocks

                        # ---------- METADATA ----------
                        invoice_data["source_files"]["status"] = (
                            "OCR_PROCESSED" if ocr_triggered else "PROCESSED"
                        )
                        invoice_data["source_files"]["page_index"] = page_index

                        invoices.append(invoice_data)

            except Exception as e:
                logger.error(f"Failed {file_path}: {traceback.format_exc()}")
                errors.append({
                    "file": os.path.basename(file_path),
                    "error": str(e)
                })

        return {
            "batch_id": batch_id,
            "scanned_at": scan_time,
            "invoice_count": len(invoices),
            "invoices": invoices,
            "errors": errors
        }

    def _perform_ocr(self, page) -> str:
        """
        Uses pdfplumber -> Pillow -> Tesseract.
        No pdf2image or OpenCV required.
        """
        try:
            # Render page to image (300 DPI is standard for OCR)
            # straight from PDF stream
            im = page.to_image(resolution=300).original
            
            # Simple pre-processing using Pillow (Greyscale)
            im = im.convert('L') 
            
            # Run Tesseract
            return pytesseract.image_to_string(im, config=self.ocr_config)
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return ""

    def _extract_invoice_data(
        self,
        lines: List[str],
        raw_text: str,
        filename: str,
        batch_id: str,
        timestamp: str,
        layout_blocks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:

        items = self._extract_items_from_blocks(lines, layout_blocks)

        # ---------------- TOTAL QTY (SAFE) ----------------
        total_qty = sum(item["qty"] for item in items if item.get("qty"))

        # ---------------- TAXABLE VALUE ----------------
        financials = self._extract_financials_from_blocks(lines, layout_blocks)

        taxable_value = financials["total_before_tax"]
        total_after_tax = financials["total_after_tax"]
        cgst = financials["cgst"]
        sgst = financials["sgst"]

        # ---------------- GST VALIDATION ----------------
        def _validated_gst(keyword: str):
            rate_str = self._find_value(lines, keyword, self.PATTERNS["percentage"])
            amt_str = self._find_value(lines, keyword, self.PATTERNS["amount"])

            if not rate_str or not amt_str or not taxable_value:
                return {"rate": None, "amount": None}

            rate = float(rate_str)
            amount = self._parse_amount(amt_str)

            # cross-check
            expected = round(taxable_value * rate / 100, 2)
            if abs(expected - amount) <= 2:
                return {"rate": rate, "amount": amount}

            return {"rate": None, "amount": None}
        return {
            "batch": batch_id,
            "type": "TAX INVOICE" if "TAX INVOICE" in raw_text.upper() else "INVOICE",
            "datetime": timestamp,
            "source_files": {
                "name": filename,
                "status": None
            },

            "invoice_details": {
                "invoice_id": self._find_label_value(lines, ["Invoice No", "Inv No", "Invoice #"]) or None,
                "invoice_date": self._extract_first_match(self.PATTERNS["date"], raw_text) or None,
                "place_of_supply": self._find_label_value(lines, ["Place of Supply"]) or None,
                "reverse_charge": (
                    "Yes" if "REVERSE CHARGE" in raw_text.upper() and "YES" in raw_text.upper()
                    else "No"
                ),
                "po_number": self._find_label_value(lines, ["PO No", "Order No"]) or None,
                "due_date": None
            },

            "company_details": {
                "company_name": self._find_entity_name(lines, is_vendor=True) or None,
                "company_address": None,
                "company_telephone": self._find_label_value(lines, ["Tel", "Phone", "Mobile"]) or None,
                "company_email": self._extract_first_match(
                    re.compile(r"[\w\.-]+@[\w\.-]+\.\w+"), raw_text
                ) or None
            },

            "company_bank_details": {
                "company_gstin": self._extract_first_match(self.PATTERNS["gstin"], raw_text) or None,
                "company_pan": self._extract_first_match(self.PATTERNS["pan"], raw_text) or None,
                "account_holder_name": None,
                "bank_name": self._find_label_value(lines, ["Bank Name"]) or None,
                "account_number": None,
                "bank_ifsc_code": self._extract_first_match(self.PATTERNS["ifsc"], raw_text) or None
            },

            "party_details": {
                "name": self._find_entity_name(lines, is_vendor=False) or None,
                "address": None,
                "gstin_number": None,
                "challan_number": self._find_label_value(lines, ["Challan No", "DC No"]) or None
            },

            "goods": {
                "items": items,
                "financials": {
                    "total_qty": total_qty,
                    "total_before_tax": taxable_value,
                    "cgst": cgst,
                    "sgst": sgst,
                    "total_after_tax": total_after_tax,
                    "total_in_words": self._find_label_value(lines, ["Amount in Words", "In Words"]) or None
                }
            }
        }

    # ================= EXTRACTION HELPERS =================

    def _extract_items_heuristic(self, lines: List[str]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        current_item: Optional[Dict[str, Any]] = None

        sr_pattern = re.compile(r"^\s*(\d{1,2})[\.\)]?\s+")
        hsn_pattern = re.compile(r"\b\d{4,8}\b")
        drg_pattern = re.compile(r"\b\d\s\d{4}\s\d{4}\s\d{4}\b")
        amount_pattern = self.PATTERNS["amount"]

        for line in lines:
            line_clean = line.strip()
            if not line_clean:
                continue

            sr_match = sr_pattern.match(line_clean)

            # ================= NEW ITEM =================
            if sr_match:
                # close previous item
                if current_item:
                    items.append(current_item)

                srno = sr_match.group(1)

                # extract amounts only if clearly present
                amounts = amount_pattern.findall(line_clean)
                price = self._parse_amount(amounts[-2]) if len(amounts) >= 2 else None
                total = self._parse_amount(amounts[-1]) if len(amounts) >= 1 else None

                # description = text after SR no, before numeric garbage
                desc_part = line_clean[sr_match.end():]
                if total is not None:
                    desc_part = desc_part.replace(str(total), "")
                description = desc_part.strip() or None

                current_item = {
                    "srno": srno,
                    "description": description,
                    "item_code": None,
                    "drg_number": drg_pattern.search(line_clean).group(0)
                        if drg_pattern.search(line_clean) else None,
                    "hsn_sac_code": hsn_pattern.search(line_clean).group(0)
                        if hsn_pattern.search(line_clean) else None,
                    "qty": 1.0,
                    "unit": "NOS",
                    "price": price,
                    "total_amount": total
                }
                continue

            # ================= CONTINUATION LINE =================
            if current_item:
                # stop appending if line is clearly totals / tax
                if any(k in line_clean.upper() for k in ["TOTAL", "CGST", "SGST", "GST", "TAXABLE", "GRAND"]):
                    continue

                # append description
                if current_item["description"]:
                    current_item["description"] += " " + line_clean
                else:
                    current_item["description"] = line_clean

                # DRG number may appear on next line
                if not current_item["drg_number"]:
                    drg_match = drg_pattern.search(line_clean)
                    if drg_match:
                        current_item["drg_number"] = drg_match.group(0)

                # HSN may appear on continuation line
                if not current_item["hsn_sac_code"]:
                    hsn_match = hsn_pattern.search(line_clean)
                    if hsn_match:
                        current_item["hsn_sac_code"] = hsn_match.group(0)

        # append last item
        if current_item:
            items.append(current_item)

        return items

    def _find_label_value(self, lines: List[str], labels: List[str]) -> Optional[str]:
        """
        STRICT label-value extractor.
        - Only accepts SAME-LINE values
        - Rejects long noisy strings
        - Never guesses
        """

        for line in lines:
            line_clean = line.strip()
            if not line_clean:
                continue

            for label in labels:
                # match: Label : Value  OR  Label - Value
                pattern = rf"\b{re.escape(label)}\b\s*[:\-]\s*(.+)"
                match = re.search(pattern, line_clean, re.IGNORECASE)
                if not match:
                    continue

                value = match.group(1).strip()

                # ---------- HARD FILTERS ----------
                # too long → likely address / garbage
                if len(value) > 60:
                    return None

                # reject if looks like another label
                if re.search(r"\b(INVOICE|DATE|GST|PAN|BANK|TEL|EMAIL|CODE)\b", value, re.IGNORECASE):
                    return None

                # reject multiline junk symbols
                if value.count("|") > 2 or value.count("=") > 2:
                    return None

                # must contain alphanumeric info
                if not re.search(r"[A-Za-z0-9]", value):
                    return None

                return value

        return None

    def _find_value(self, lines: List[str], keyword: str, regex) -> Optional[str]:
        """
        Finds a specific keyword line, then extracts value using regex.
        """
        for line in lines:
            if keyword.lower() in line.lower():
                match = regex.search(line)
                if match:
                    return match.group(1)
        return None

    def _extract_first_match(self, pattern, text: str) -> str:
        match = pattern.search(text)
        return match.group(0) if match else ""

    def _parse_amount(self, value_str: Optional[str]) -> float:
        if not value_str:
            return 0.0
        try:
            return float(value_str.replace(",", "").replace("INR", "").strip())
        except ValueError:
            return 0.0

    def _find_entity_name(self, lines: List[str], is_vendor: bool) -> Optional[str]:

        def is_valid_name(text: str) -> bool:
            text_u = text.upper()

            # reject obvious noise
            if any(x in text_u for x in [
                "@", "GST", "PAN", "PHONE", "TEL", "EMAIL",
                "INVOICE", "DATE", "NO.", "CODE", "IFSC",
                "BANK", "A/C", "ACCOUNT", "MOBILE"
            ]):
                return False

            # reject address-like lines
            if re.search(r"\d{5,6}", text):  # pincode
                return False
            if "," in text and len(text.split(",")) > 2:
                return False

            # must contain alphabetic words
            return bool(re.search(r"[A-Z]{3,}", text_u))

        # ================= VENDOR =================
        if is_vendor:
            for line in lines[:10]:
                line = line.strip()
                if not line:
                    continue

                if any(x in line.upper() for x in [
                    "PVT", "PRIVATE", "LTD", "LIMITED",
                    "ENGINEERS", "ENGINEERING",
                    "WORKS", "INDUSTRIES", "FABRICATION"
                ]):
                    if is_valid_name(line):
                        return line

            return None

        # ================= PARTY / BUYER =================
        bill_to_idx = None
        for i, line in enumerate(lines):
            if any(x in line.upper() for x in ["BILL TO", "INVOICE TO", "BUYER"]):
                bill_to_idx = i
                break

        if bill_to_idx is None:
            return None

        # scan next few lines only
        for line in lines[bill_to_idx + 1: bill_to_idx + 6]:
            line = line.strip()
            if not line:
                continue

            if is_valid_name(line):
                return line

        return None