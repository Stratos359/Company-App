import os
import re
import time
import unicodedata
import email
from email.header import decode_header
from dotenv import load_dotenv
import imapclient
from pdf2image import convert_from_path
import pytesseract
import pdfplumber
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler

import pytesseract
import os

# Explicitly set tesseract path for Render
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"


# --------------------------- Load environment ---------------------------
load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
PAYROLL_EMAIL = os.getenv("PAYROLL_EMAIL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --------------------------- Folders ---------------------------
BASE_DIR = "attachments"
PAYROLLS_DIR = os.path.join(BASE_DIR, "payrolls")
INVOICES_DIR = os.path.join(BASE_DIR, "invoices")

os.makedirs(PAYROLLS_DIR, exist_ok=True)
os.makedirs(INVOICES_DIR, exist_ok=True)

INVOICE_KEYWORDS = ["ΤΙΜΟΛΟΓΙΟ", "ΤΙΜΟΛΟΓΙΑ", "τιμολόγιο"]

# --------------------------- Utilities ---------------------------
def decode_mime_filename(s):
    if not s:
        return "unknown.pdf"
    parts = decode_header(s)
    filename = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            filename += text.decode(enc or "utf-8", errors="ignore")
        else:
            filename += text
    return "".join(c for c in filename if c not in r'\/:*?"<>|')

def normalize_text(text: str) -> str:
    text = text.lower().replace(" ", "")
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')

def format_amount(value: str) -> str:
    try:
        amount = float(value.replace(",", ".").replace(" ", ""))
        return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return value

def sanitize_filename(filename: str) -> str:
    """
    Convert filename to URL-safe ASCII for Supabase Storage.
    Replaces spaces and invalid characters with underscores.
    """
    # Normalize unicode to ASCII
    filename_ascii = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    # Replace spaces and invalid chars with underscore
    filename_safe = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename_ascii)
    # Collapse multiple underscores
    filename_safe = re.sub(r'_+', '_', filename_safe)
    return filename_safe.strip('_')

# --------------------------- Save attachments ---------------------------
def save_pdf_attachments():
    with imapclient.IMAPClient('imap.gmail.com') as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.select_folder('INBOX')
        messages = server.search(['UNSEEN'])
        print(f"Found {len(messages)} unseen emails")
        for uid, message_data in server.fetch(messages, ['RFC822']).items():
            msg = email.message_from_bytes(message_data[b'RFC822'])
            sender = msg.get("From", "").lower()
            subject = msg.get("Subject", "").lower()
            if PAYROLL_EMAIL.lower() in sender:
                folder = PAYROLLS_DIR
            elif any(kw.lower() in subject for kw in INVOICE_KEYWORDS):
                folder = INVOICES_DIR
            else:
                folder = INVOICES_DIR
            for part in msg.walk():
                if part.get_content_type() == "application/pdf":
                    raw_filename = part.get_filename()
                    if raw_filename:
                        filename = decode_mime_filename(raw_filename)
                        filepath = os.path.join(folder, filename)
                        with open(filepath, "wb") as f:
                            f.write(part.get_payload(decode=True))
                        print(f"Saved PDF: {filepath}")

# --------------------------- Upload PDF to Supabase ---------------------------
def upload_pdf_to_supabase(table_name: str, pdf_path: str) -> str:
    """
    Upload a PDF to Supabase Storage under the folder matching table_name.
    Returns the public URL of the uploaded file.
    """
    try:
        filename = os.path.basename(pdf_path)
        # Prepend timestamp to avoid collisions and sanitize
        filename_with_ts = f"{int(time.time())}_{sanitize_filename(filename)}"

        with open(pdf_path, "rb") as f:
            supabase.storage.from_(table_name).upload(filename_with_ts, f)

        # Generate public URL
        url = supabase.storage.from_(table_name).get_public_url(filename_with_ts)
        print(f"Uploaded {pdf_path} → {url}")
        return url

    except Exception as e:
        print(f"Failed to upload {pdf_path}: {e}")
        return ""

# --------------------------- Payroll parsers ---------------------------
def extract_employee_name(lines):
    for i, line in enumerate(lines):
        if "ΣΤΟΙΧΕΙΑ ΕΡΓΑΖΟΜΕΝΟΥ" in line:
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                words = [w for w in candidate.split() if re.match(r'^[A-Za-zΑ-Ωα-ωΆ-Ώά-ώ]+$', w)]
                if len(words) >= 2:
                    return words[0], words[1]
    return None, None

def extract_amount(lines):
    for line in lines:
        if "Πληρωτέες Αποδοχές" in line:
            match = re.search(r'[\d.,]+', line)
            if match:
                return match.group()
    return None

def extract_reason(lines):
    for line in lines:
        if "ΜΙΣΘΟΔΟΣΙΑΣ" in line:
            reason = line.replace("ΕΞΟΦΛΗΤΙΚΗ ΑΠΟΔΕΙΞΗ ", "")
            reason = reason.replace("ΜΙΣΘΟΔΟΣΙΑΣ", "ΜΙΣΘΟΔΟΣΙΑ")
            return reason.strip()
    return None

def parse_ika(lines):
    date, amount, rf_code = None, None, None
    for i, line in enumerate(lines):
        norm = line.replace(" ", "").replace(";", "").replace(":", "")
        if "ΗμερομηνίαΥποβολής" in norm:
            match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", line)
            if match:
                date = match.group(1).replace("96/", "06/")
        if "ΣύνολοΕισφορών" in norm:
            match = re.search(r"(\d+[.,]?\d*)", line)
            if match:
                amount = format_amount(match.group(1))
        if "τ.Π.Τ.Ε" in norm or "τ.Π.Τ.Ε." in norm:
            for j in range(i+1, min(i+6, len(lines))):
                candidate = lines[j].strip()
                if candidate.upper().startswith("RF"):
                    rf_code = candidate
                    break
    return {"reason":"ΙΚΑ","date":date,"amount":amount,"code":rf_code,"paid":False}

def parse_debt(lines):
    text_joined = " ".join(lines)
    amount, date, rf_code = None, None, None
    amt_match = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2}))\s*€", text_joined)
    if amt_match:
        amount = format_amount(amt_match.group(1))
    numbers = re.findall(r'\d{9,}', text_joined)
    if numbers and len(numbers) > 1:
        rf_code = " ".join(numbers[1:])
    date_match = re.search(r"Ημ/νία\s*Έκδοσης\s*(\d{1,2}/\d{1,2}/\d{4})", text_joined, re.IGNORECASE)
    if date_match:
        date = date_match.group(1)
    return {"reason":"ΒΕΒΑΙΩΜΕΝΕΣ ΟΦΕΙΛΕΣ","date":date,"amount":amount,"code":rf_code,"paid":False}

def parse_payroll(lines):
    surname, name = extract_employee_name(lines)
    amount = extract_amount(lines)
    reason = extract_reason(lines)
    return {"reason":reason,"surname":surname,"name":name,"amount":format_amount(amount) if amount else None,"paid":False}

def parse_payroll_pdf(pdf_path):
    pages = convert_from_path(pdf_path)
    results = []
    for page in pages:
        text = pytesseract.image_to_string(page, lang='ell+eng')
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if any("ΑΝΤΙΓΡΑΦΟ" in l and ("ΑΠΔ" in l or "ANA" in l) for l in lines):
            record = parse_ika(lines)
        elif any("πληρωμή βεβαιωμένων οφειλών" in l.lower() for l in lines):
            record = parse_debt(lines)
        else:
            record = parse_payroll(lines)
        if any(record.values()):
            results.append(record)
    return results

# --------------------------- Invoice parsers ---------------------------
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
            top_crop = page.crop((0, 0, page.width, 120))
            text += pytesseract.image_to_string(top_crop, lang='ell')
            text += pytesseract.image_to_string(page, lang='ell')
    return text

def extract_vendor(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines:
        if line.startswith("Επωνυμία"):
            return line.split(":",1)[-1].strip() if ":" in line else line.replace("Επωνυμία","").strip()
    return lines[0] if lines else None

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
    return {"vendor":vendor,"date":date,"amount":amount,"paid":False}

# --------------------------- Main processing ---------------------------
def process_all():
    save_pdf_attachments()

    # Payrolls
    for pdf_file in os.listdir(PAYROLLS_DIR):
        if pdf_file.lower().endswith(".pdf"):
            pdf_path = os.path.join(PAYROLLS_DIR, pdf_file)
            records = parse_payroll_pdf(pdf_path)
            file_url = upload_pdf_to_supabase("payrolls", pdf_path)
            for rec in records:
                rec["file_url"] = file_url
                supabase.table("payrolls").insert(rec).execute()
            os.remove(pdf_path)

    # Invoices
    for pdf_file in os.listdir(INVOICES_DIR):
        if pdf_file.lower().endswith(".pdf"):
            pdf_path = os.path.join(INVOICES_DIR, pdf_file)
            rec = parse_invoice_from_pdf(pdf_path)
            rec["file_url"] = upload_pdf_to_supabase("invoices", pdf_path)
            supabase.table("invoices").insert(rec).execute()
            os.remove(pdf_path)

# --------------------------- Scheduler ---------------------------
if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(process_all, "interval", minutes=5)
    scheduler.start()
    print("PDF parser background service running. Press Ctrl+C to exit.")
    try:
        while True:
            pass
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

