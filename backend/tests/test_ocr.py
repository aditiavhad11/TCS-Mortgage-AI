"""PDF OCR tests; need PyMuPDF + Tesseract (skipped where unavailable)."""
import shutil
from pathlib import Path
import pytest
fitz = pytest.importorskip("fitz")
from app.services.ocr import extract_text

def test_embedded_pdf_text_extraction(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    doc = fitz.open(); page = doc.new_page()
    page.insert_text((72, 72), "Synthetic mortgage agreement. Property value INR 4500000.")
    doc.save(pdf); doc.close()
    text, status, message = extract_text(pdf)
    assert status == "COMPLETED" and "Property value INR 4500000" in text and "embedded" in message

@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_scanned_pdf_uses_ocr(tmp_path: Path):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 260), "white"); ImageDraw.Draw(img).text((30, 90), "Loan amount INR 3000000", fill="black", font=ImageFont.load_default(size=44))
    png = tmp_path / "s.png"; img.save(png)
    pdf = tmp_path / "scan.pdf"; doc = fitz.open(); page = doc.new_page(width=700, height=130); page.insert_image(page.rect, filename=str(png)); doc.save(pdf); doc.close()
    text, status, message = extract_text(pdf)
    assert status == "COMPLETED" and "3000000" in text.replace(",", "").replace(" ", "") and "Tesseract" in message

def test_mixed_pdf_ocrs_only_scanned_pages(tmp_path: Path):
    if not shutil.which("tesseract"): pytest.skip("tesseract not installed")
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 260), "white"); ImageDraw.Draw(img).text((30, 90), "Valuation INR 5200000", fill="black", font=ImageFont.load_default(size=44))
    png = tmp_path / "s.png"; img.save(png)
    doc = fitz.open(); doc.new_page().insert_text((72, 72), "Page one has embedded text for the mortgage application form.")
    doc.new_page(width=700, height=130).insert_image(fitz.Rect(0, 0, 700, 130), filename=str(png))
    pdf = tmp_path / "mixed.pdf"; doc.save(pdf); doc.close()
    text, status, message = extract_text(pdf)
    assert "embedded text" in text and "5200000" in text.replace(",", "").replace(" ", "") and "1 page(s) from embedded" in message
