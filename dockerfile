# ---------------------------
# Base image
# ---------------------------
FROM python:3.11-slim

# ---------------------------
# Set environment variables
# ---------------------------
ENV PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8

# ---------------------------
# Install system dependencies
# ---------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-ell \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------
# Set work directory
# ---------------------------
WORKDIR /app

# ---------------------------
# Copy project files
# ---------------------------
COPY requirements.txt .
COPY . .

# ---------------------------
# Install Python dependencies
# ---------------------------
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------
# Create folders for attachments
# ---------------------------
RUN mkdir -p attachments/payrolls attachments/invoices attachments/processed

# ---------------------------
# Set entrypoint
# ---------------------------
CMD ["python", "main.py"]


