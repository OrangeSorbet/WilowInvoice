import json
import pdfplumber
import paddle
from paddleocr import PaddleOCR

# -----------------------
# Force CPU (safe default)
paddle.set_device("cpu")

# -----------------------
# Initialize PaddleOCR
ocr_model = PaddleOCR(
    lang="en",
    use_textline_orientation=True
)

# -----------------------
import numpy as np

def extract_blocks_from_pdf(pdf_path):
    blocks = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            pil_image = page.to_image(resolution=300).original
            image_np = np.array(pil_image)

            result = ocr_model.predict(image_np)

            if not result or not result[0]:
                continue

            for line in result[0]:
                bbox = line[0]      # 4-point polygon
                text = line[1][0]
                score = line[1][1]

                blocks.append({
                    "page": page_num,
                    "bbox": bbox,
                    "text": text,
                    "confidence": score
                })

    return blocks


# -----------------------
def save_blocks_to_json(blocks, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(blocks, f, indent=2, ensure_ascii=False)

# -----------------------
if __name__ == "__main__":
    pdf_file = r"C:\Users\ashvi\Documents\VS_Codes\Python\WiloInvoice\sampleinvoices\Four_Sample_Supplier_Invoices-2.pdf"
    output_file = "Four_Sample_Supplier_Invoices-2_blocks.json"

    blocks = extract_blocks_from_pdf(pdf_file)
    save_blocks_to_json(blocks, output_file)

    print(f"Extracted {len(blocks)} OCR blocks → {output_file}")
