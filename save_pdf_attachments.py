import imapclient
import email
from email.header import decode_header
from dotenv import load_dotenv
import os

load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

BASE_DIR = "attachments"
INVOICES_DIR = os.path.join(BASE_DIR, "invoices")
PAYROLLS_DIR = os.path.join(BASE_DIR, "payrolls")

# Define sender addresses or subject keywords
PAYROLL_EMAIL = os.getenv("PAYROLL_EMAIL")  # payroll sender

INVOICE_KEYWORDS = ["ΤΙΜΟΛΟΓΙΟ", "ΤΙΜΟΛΟΓΙΑ", "τιμολόγιο"]

# Ensure directories exist
os.makedirs(INVOICES_DIR, exist_ok=True)
os.makedirs(PAYROLLS_DIR, exist_ok=True)

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
    # Remove invalid characters for Windows filenames
    return "".join(c for c in filename if c not in r'\/:*?"<>|')

def save_pdf_attachments():
    with imapclient.IMAPClient('imap.gmail.com') as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.select_folder('INBOX')

        messages = server.search(['UNSEEN'])
        print(f"Found {len(messages)} unseen emails")

        for uid, message_data in server.fetch(messages, ['RFC822']).items():
            msg = email.message_from_bytes(message_data[b'RFC822'])

            # Determine folder
            sender = msg.get("From", "").lower()
            subject = msg.get("Subject", "")
            subject_lower = subject.lower()

            if PAYROLL_EMAIL.lower() in sender:
                folder = PAYROLLS_DIR
            elif any(kw.lower() in subject_lower for kw in INVOICE_KEYWORDS):
                folder = INVOICES_DIR
            else:
                folder = INVOICES_DIR  # default to invoices

            for part in msg.walk():
                if part.get_content_type() == "application/pdf":
                    raw_filename = part.get_filename()
                    if raw_filename:
                        filename = decode_mime_filename(raw_filename)
                        filepath = os.path.join(folder, filename)
                        with open(filepath, "wb") as f:
                            f.write(part.get_payload(decode=True))
                        print(f"Saved PDF: {filepath}")


if __name__ == "__main__":
    save_pdf_attachments()