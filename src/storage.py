import sqlite3
import pandas as pd
from datetime import datetime
from .security import SecurityManager

class StorageEngine:
    def __init__(self, db_path="invoices.db"):
        self.db_path = db_path
        self.sec = SecurityManager()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        # Stores meta-data in clear, sensitive data as BLOB (Encrypted)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE,
                filename TEXT,
                upload_date TEXT,
                vendor_enc BLOB,
                total_enc BLOB,
                json_data_enc BLOB,
                status TEXT
            )
        """)
        conn.commit()
        conn.close()

    def save_invoice(self, filename, file_hash, data_dict):
        # Encrypt sensitive fields
        vendor_enc = self.sec.encrypt_data(data_dict.get('vendor', 'Unknown'))
        total_enc = self.sec.encrypt_data(str(data_dict.get('total', '0.00')))
        json_enc = self.sec.encrypt_data(str(data_dict)) # Full dump

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO invoices (file_hash, filename, upload_date, vendor_enc, total_enc, json_data_enc, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (file_hash, filename, datetime.now().isoformat(), vendor_enc, total_enc, json_enc, "PROCESSED"))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False # Duplicate
        finally:
            conn.close()

    def export_to_csv(self, output_path):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT * FROM invoices").fetchall()
        conn.close()

        # Decrypt for export
        cleaned_data = []
        for r in rows:
            cleaned_data.append({
                "ID": r[0],
                "Filename": r[2],
                "Date": r[3],
                "Vendor": self.sec.decrypt_data(r[4]),
                "Total": self.sec.decrypt_data(r[5]),
                "Status": r[7]
            })
        
        df = pd.DataFrame(cleaned_data)
        df.to_csv(output_path, index=False)
        return len(df)