# 📄 Wilow Invoice Extractor

**Version:** 1.0  
**Type:** Desktop / Offline  
**Security Level:** Enterprise  

---

## 1. Executive Summary

The **Wilow Invoice Extractor** is a standalone, offline-first desktop application designed to automate the ingestion, extraction, and validation of vendor invoices. It replaces manual data entry with a secure, automated pipeline capable of processing both digital and scanned PDFs, enforcing strict data validation, and exporting structured data (CSV/JSON/DB) without requiring technical setup or internet connectivity.

---

## 2. Logical Architecture Diagram

The system follows a **moduled, separation-of-concerns** architecture. The UI is strictly decoupled from the processing core to ensure responsiveness and security.
```
┌───────────────────────────────────────────────────────────┐
│                  Presentation Layer (UI)                  │
│                       PySide6 Desktop                     │
│                                                           │
│   ┌──────────────┐        ┌───────────────────────────┐   │
│   │   User UI    │──────▶ │     Input Validator      │   │
│   └──────────────┘        └───────────────────────────┘   │
│           │                               │               │
│           ▼                               ▼               │
│   ┌─────────────────┐         ┌────────────────────────┐  │
│   │ Progress / Logs │◀────── │   Secure Logger        │  │
│   └─────────────────┘         └────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────┐
│                  Secure Processing Core                   │
│                     Python 3.11+                          │
│                                                           │
│   ┌───────────────────┐                                   │
│   │ Ingestion Engine  │                                   │
│   │  - MIME Check     │                                   │
│   │  - Hashing        │                                   │
│   │  - Quarantine     │                                   │
│   └─────────┬─────────┘                                   │
│             │                                             │
│     ┌───────┴────────┐                                    │
│     │  File Router   │                                    │
│     └───────┬────────┘                                    │
│             │                                             │
│   ┌─────────▼─────────┐      ┌────────────────────────┐   │
│   │ Digital PDF Parser│      │ OCR Engine (Tesseract) │   │
│   │  (Poppler)        │      │  - Isolated Process    │   │
│   └─────────┬─────────┘      └──────────┬─────────────┘   │
│             │                           │                 │
│             └──────────────┬────────────┘                 │
│                            ▼                              │
│              ┌──────────────────────────────┐             │
│              │     Intelligence Engine      │             │
│              │                              │             │
│              │  ┌────────┐  ┌──────────┐    │             │
│              │  │ Regex  │  │ NLP / NER│    │             │
│              │  └────────┘  └──────────┘    │             │
│              │        ┌────────────────┐    │             │
│              │        │ Table Extract  │    │             │
│              │        └────────────────┘    │             │
│              └──────────────┬───────────────┘             │
│                             ▼                             │
│                 ┌────────────────────────┐                │
│                 │   Data Validator       │                │
│                 │ - Totals Check         │                │
│                 │ - Tax Validation       │                │
│                 │ - Fraud Heuristics     │                │
│                 └──────────┬─────────────┘                │
└───────────────────────────────────────────────────────────┘
                          │
                          ▼
┌───────────────────────────────────────────────────────────┐
│                 Storage & Export Layer                    │
│                                                           │
│   ┌──────────────────────────────┐                        │
│   │ Encrypted SQLite (SQLCipher) │                        │
│   └───────────────┬──────────────┘                        │
│                   ▼                                       │
│         ┌───────────────────────────┐                     │
│         │     Export Service        │                     │
│         │  - CSV (Sanitized)        │                     │
│         │  - Excel                  │                     │
│         │  - JSON                   │                     │
│         └───────────────────────────┘                     │
└───────────────────────────────────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────────┐
│              Cross-Cutting Security Services              │
│                                                           │
│   ┌─────────────────┐  ┌─────────────────┐  ┌───────────┐ │
│   │ Encryption Mgr  │  │ Secure Logger   │  │ License   │ │
│   │ AES-256 / PBKDF │  │ Redacted Logs   │  │ Integrity │ │
│   └─────────────────┘  └─────────────────┘  └───────────┘ │
└───────────────────────────────────────────────────────────┘
```
---

## 3. Secure Data Lifecycle (End-to-End Flow)

This flow ensures data is protected at rest, in transit (internal memory), and during processing.

### Phase 1: Ingestion & Quarantine

* **Action:** User selects a PDF.
* **Security:** File is **never** opened directly.
* **MIME Validation:** `python-magic` confirms it is a PDF (prevents renaming `.exe` to `.pdf`).
* **Sandboxing:** File is copied to a temporary, isolated directory with read-only permissions.
* **Hash Generation:** SHA-256 hash generated to detect duplicate invoices immediately.

---

### Phase 2: Extraction (The "Black Box")

* **Action:** Text is extracted via `pdfplumber` (digital) or `Tesseract` (scanned).
* **Security:**

  * **Subprocess Isolation:** OCR runs in a restricted subprocess with no shell access (`shell=False`).
  * **Resource Limits:** Strict timeout and memory caps to prevent DoS via massive files.
  * **Memory Hygiene:** Extracted text is stored in encrypted memory buffers where possible; sensitive temp files are encrypted at rest.

---

### Phase 3: Intelligence & Validation

* **Action:** Hybrid engine (Regex + NLP) parses the text.
* **Logic:**

  * **Extraction:** Identifies Vendor, Date, Line Items, and Totals.
  * **Reconciliation:** `Sum(Line Items) == Grand Total`? `Tax %` matches logical calculation?
  * **Fraud Check:** Does the bank account match the vendor record? Is the invoice date in the future?

---

### Phase 4: Output & Cleanup

* **Action:** Data is saved to Encrypted SQLite or exported.
* **Security:**

  * **Sanitization:** Export data is escaped to prevent **CSV Injection** (Excel formula attacks).
  * **Wiping:** On application close, all temporary files are securely deleted (overwritten), and encryption keys are dropped from memory.

---

## 4. Threat Model (STRIDE Analysis)

| Category              | Threat                                                    | Mitigation Strategy                                                                                                                    |
| --------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Spoofing**          | Malicious actor submits fake invoices from known vendors. | **Digital Signature Validation** (if available) & **Historical Baseline** checks (e.g., "Vendor X usually charges $500, not $50,000"). |
| **Tampering**         | Modifying the PDF structure to crash the parser.          | **Strict Input Sanitization**; catch-all exception handlers around parsing logic; specific PDF compliance checks.                      |
| **Repudiation**       | User claims they didn't process a specific invoice.       | **Immutable Local Audit Logs** (encrypted) recording filename, hash, timestamp, and user action.                                       |
| **Info Disclosure**   | Sensitive financial data leaked via temp files or logs.   | **AES-256 Encryption** for temp files; **Redacted Logging** (no PII/financials in logs); **Memory Wiping** on exit.                    |
| **Denial of Service** | Massive or malformed PDF causing app freeze.              | **File Size Limits** (e.g., max 20MB); **Page Count Limits**; **Regex Timeouts** to prevent ReDoS attacks.                             |
| **Elevation of Priv** | Malicious PDF executes code via parser vulnerability.     | **Nuitka Compilation** (hardened binary); **No `eval()` / `exec()` usage**; OCR runs with least privilege.                             |

---

## 5. Enterprise Security Specifications

### A. Cryptographic Standards

* **At Rest:** AES-256 (via SQLCipher for DB, Fernet for temp files).
* **Key Management:** Keys derived via PBKDF2-HMAC-SHA256; keys never stored on disk in plaintext.
* **Integrity:** Application binary signed and checksummed to detect tampering.

---

### B. Application Hardening

* **Compilation:** Built using **Nuitka** (compiles Python to C) to prevent reverse engineering of proprietary extraction logic.
* **Obfuscation:** Variable and function name obfuscation provided by the compiler.
* **Anti-Debug:** Basic checks to detect if the application is running under a debugger.

---

### C. Compliance & Privacy

* **Offline Guarantee:** The application has **zero outbound network calls**. This is a critical selling point for GDPR and data privacy compliance, ensuring financial data never leaves the user's machine.

---

## FOR DEVELOPERS

ALWAYS ACTIVATE VIRTUAL ENVIRONMENT IN TERMINAL BEFORE INSTALLING ANYTHING  
**Python 3.11.9**  
```
.venv/Scripts/activate
```
```
python -m spacy download en_core_web_sm
```
```
pip install -r requirements.txt
```

You also need Poppler-25.12.0 AND Tesseract  
Find the files attached in `prereq/` (install Tesseract directly, include Math symbols, Hindi, Marathi)  
Add path to "System Variables" for Poppler under Path (after moving Poppler folder to C: drive)  
This is an example path `C:\poppler-25.12.0\Library\bin`  
 
Run `build.py` for building the project and you will find the product in `dist/`  
To get rid of Nuitka cache bloatware, simply delete `C:\Users\User\AppData\Local\Nuitka\`  
Example - `C:\Users\User\AppData\Local\Nuitka\Nuitka\Cache\DOWNLO~1\`  

---
