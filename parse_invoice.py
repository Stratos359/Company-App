import pdfplumber
import pytesseract
from pdf2image import convert_from_path
import re
import os

# Folder where PDFs are saved
INVOICES_DIR = "attachments/invoices"

# ------------------------
# Configuration
# ------------------------

# Poppler path: replace with your Poppler bin folder
POPPLER_PATH = r"C:\Users\strat\Downloads\poppler-25.07.0\Library\bin"  # <-- UPDATE this path

# Optional: specify Tesseract path if not in PATH
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ------------------------
# Helper functions
# ------------------------

def find_first_match(text, patterns):
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            return match.group(1).strip()
    return None

def extract_text_from_pdf(filepath):
    text = ""
    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    except:
        pass
    if len(text.strip()) < 20:
        pages = convert_from_path(filepath)
        for page in pages:
            text += pytesseract.image_to_string(page, lang='ell')
    return text

def extract_vendor(text):
    """Extract vendor name: first look for 'Επωνυμία', fallback to first line."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    # 1️⃣ Look for line starting with Επωνυμία
    for line in lines:
        if line.startswith("Επωνυμία"):
            return line.split(":", 1)[-1].strip() if ":" in line else line.replace("Επωνυμία", "").strip()
    
    # 2️⃣ Fallback: first non-empty line
    if lines:
        return lines[0]
    
    return None

def normalize_amount(amount_str):
    if not amount_str:
        return None
    amount_str = amount_str.replace("€","").replace(" ","")
    if "," in amount_str and amount_str.count(",")==1:
        amount_str = amount_str.replace(",",".")
    amount_str = amount_str.replace(".","") if amount_str.count(".")>1 else amount_str
    try:
        return float(amount_str)
    except:
        return None

def parse_invoice_from_pdf(filepath):
    raw_text = extract_text_from_pdf(filepath)
    vendor = extract_vendor(raw_text)
    date_match = re.search(r'([0-3]?\d/[0-1]?\d/[0-9]{4})', raw_text)
    date = date_match.group(1) if date_match else None
    amount_patterns = [r'Πληρωτ[έε]ο\s*\(ε\)', r'Πληρωτ[έε]ο Ποσό', r'Συνολική Αξία', r'Τελική Αξία', r'Συν\. Αξία']
    amount = None
    for pat in amount_patterns:
        match = re.search(pat + r'\s*:\s*([\d.,]+)', raw_text, re.IGNORECASE)
        if match:
            amt = normalize_amount(match.group(1))
            if amt is not None:
                amount = "{:.2f}".format(amt)
            break
    return {"vendor": vendor, "date": date, "amount": amount}

all_results = []

def parse_all_pdfs():
    for filename in os.listdir(INVOICES_DIR):
        if filename.lower().endswith(".pdf"):
            filepath = os.path.join(INVOICES_DIR, filename)
            parsed = parse_invoice_from_pdf(filepath)
            all_results.append(parsed)   # save dict, no filename attached

# ------------------------
# Run script
# ------------------------
if __name__ == "__main__":
    parse_all_pdfs()
    for r in all_results:
        print(r)


