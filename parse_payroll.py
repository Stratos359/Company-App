import os
import re
import unicodedata
from pdf2image import convert_from_path
import pytesseract

PAYROLLS_DIR = "attachments/payrolls"  # your payrolls directory
POPPLER_PATH = r"C:\Users\strat\Downloads\poppler-25.07.0\Library\bin"  # your poppler bin folder


# ---------------------------
# Utilities
# ---------------------------

def normalize_text(text: str) -> str:
    """Normalize OCR text: lowercase, strip spaces, remove accents."""
    text = text.lower().replace(" ", "")
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')


def format_amount(value: str) -> str:
    """Convert OCR number to standardized format (1.234,56)."""
    try:
        amount = float(value.replace(",", ".").replace(" ", ""))
        return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return value


# ---------------------------
# Extractors for payroll pages
# ---------------------------

def extract_employee_name(lines):
    for i, line in enumerate(lines):
        if "ΣΤΟΙΧΕΙΑ ΕΡΓΑΖΟΜΕΝΟΥ" in line:
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                words = [w for w in candidate.split() if re.match(r'^[A-Za-zΑ-Ωα-ωΆ-Ώά-ώ]+$', w)]
                if len(words) >= 2:
                    return words[0], words[1]  # surname, name
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


# ---------------------------
# Parsers for each type
# ---------------------------

def parse_ika(lines):
    date, amount, rf_code = None, None, None
    for i, line in enumerate(lines):
        norm = line.replace(" ", "").replace(";", "").replace(":", "")
        # Date
        if "ΗμερομηνίαΥποβολής" in norm:
            match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", line)
            if match:
                date = match.group(1)
                # OCR misread fix
                if date.startswith("96/"):
                    date = "06/" + date[3:]

        # Amount
        if "ΣύνολοΕισφορών" in norm:
            match = re.search(r"(\d+[.,]?\d*)", line)
            if match:
                amount = format_amount(match.group(1))

        # RF code (Τ.Π.Τ.Ε)
        if re.search(r'Τ\.Π\.Τ\.Ε', line.replace(" ", "")):
            # grab next non-empty line that looks like a code
            for j in range(i + 1, min(i + 5, len(lines))):
                candidate = lines[j].strip()
                if candidate and re.match(r'[\dA-Z-]+', candidate):
                    rf_code = candidate
                    break

    return {
        "reason": "ΙΚΑ",
        "date": date,
        "amount": amount,
        "code": rf_code
    }




def parse_debt(lines):
    text_joined = " ".join(lines)
    amount, date, rf_code = None, None, None

    # Extract amount
    amt_match = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2}))\s*€", text_joined)
    if amt_match:
        amount = format_amount(amt_match.group(1))

    # Extract code (ignore first AFM number)
    numbers = re.findall(r'\d{9,}', text_joined)
    if numbers and len(numbers) > 1:
        rf_code = " ".join(numbers[1:])

    # Extract date
    date_match = re.search(r"Ημ/νία\s*Έκδοσης\s*(\d{1,2}/\d{1,2}/\d{4})", text_joined, re.IGNORECASE)
    if date_match:
        date = date_match.group(1)

    return {
        "reason": "ΒΕΒΑΙΩΜΕΝΕΣ ΟΦΕΙΛΕΣ",
        "date": date,
        "amount": amount,
        "code": rf_code
    }


def parse_payroll(lines):
    surname, name = extract_employee_name(lines)
    amount = extract_amount(lines)
    reason = extract_reason(lines)
    return {
        "reason": reason,
        "surname": surname,
        "name": name,
        "amount": format_amount(amount) if amount else None,
    }


# ---------------------------
# Main dispatcher
# ---------------------------

def parse_payroll_pdf(pdf_path):
    pages = convert_from_path(pdf_path, poppler_path=POPPLER_PATH)
    results = []

    for page in pages:
        text = pytesseract.image_to_string(page, lang='ell+eng')
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        if any("ΑΝΤΙΓΡΑΦΟ" in l and ("ΑΠΔ" in l or "ANA" in l) for l in lines):
            record = parse_ika(lines)
        elif any("πληρωμή βεβαιωμένων οφειλών" in l.lower() for l in lines):
            record = parse_debt(lines)
        else:
            record = parse_payroll(lines)

        # Skip empty records
        if any(v for v in record.values()):
            results.append(record)

    return results


# ---------------------------
# Run parser on all files
# ---------------------------

if __name__ == "__main__":
    all_results = []
    for pdf_file in os.listdir(PAYROLLS_DIR):
        if pdf_file.lower().endswith(".pdf"):
            pdf_path = os.path.join(PAYROLLS_DIR, pdf_file)
            all_results.extend(parse_payroll_pdf(pdf_path))

    for r in all_results:
        print(r)






