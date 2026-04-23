# tests/engine/test_multimodal.py
import base64
import pytest
from marneo.engine.chat import _build_content_blocks


def test_build_content_blocks_text_only():
    """No attachments → return plain string."""
    result = _build_content_blocks(text="hello", attachments=[], protocol="openai-compatible")
    assert result == "hello"


def test_build_content_blocks_image_openai():
    """Image with OpenAI protocol → image_url content block."""
    att = {"data": b"\xff\xd8\xff", "media_type": "image/jpeg", "filename": "photo.jpg"}
    blocks = _build_content_blocks(text="what is this?", attachments=[att], protocol="openai-compatible")
    assert isinstance(blocks, list)
    text_blocks = [b for b in blocks if b.get("type") == "text"]
    image_blocks = [b for b in blocks if b.get("type") == "image_url"]
    assert len(text_blocks) == 1
    assert text_blocks[0]["text"] == "what is this?"
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_build_content_blocks_image_anthropic():
    """Image with Anthropic protocol → image source block."""
    att = {"data": b"\xff\xd8\xff", "media_type": "image/jpeg", "filename": "photo.jpg"}
    blocks = _build_content_blocks(text="describe", attachments=[att], protocol="anthropic-compatible")
    assert isinstance(blocks, list)
    image_blocks = [b for b in blocks if b.get("type") == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["type"] == "base64"
    assert image_blocks[0]["source"]["media_type"] == "image/jpeg"


def test_build_content_blocks_pdf_anthropic():
    """PDF with Anthropic protocol → document block."""
    att = {"data": b"%PDF-1.4", "media_type": "application/pdf", "filename": "doc.pdf"}
    blocks = _build_content_blocks(text="summarize", attachments=[att], protocol="anthropic-compatible")
    assert isinstance(blocks, list)
    doc_blocks = [b for b in blocks if b.get("type") == "document"]
    assert len(doc_blocks) == 1
    assert doc_blocks[0]["source"]["media_type"] == "application/pdf"


def test_build_content_blocks_pdf_openai_injects_notice():
    """PDF with OpenAI protocol → text notice (no native PDF support)."""
    att = {"data": b"%PDF-1.4 content", "media_type": "application/pdf", "filename": "report.pdf"}
    blocks = _build_content_blocks(text="compare", attachments=[att], protocol="openai-compatible")
    if isinstance(blocks, list):
        all_text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    else:
        all_text = str(blocks)
    assert "report.pdf" in all_text


def test_build_content_blocks_text_file_injected():
    """Plain text file → content injected as text block."""
    att = {"data": b"name,age\nAlice,30", "media_type": "text/plain", "filename": "data.csv"}
    blocks = _build_content_blocks(text="analyze", attachments=[att], protocol="openai-compatible")
    if isinstance(blocks, list):
        all_text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    else:
        all_text = str(blocks)
    assert "Alice" in all_text
    assert "data.csv" in all_text


def test_build_content_blocks_empty_data_skipped():
    """Attachment with empty data is silently skipped."""
    att = {"data": b"", "media_type": "image/jpeg", "filename": "empty.jpg"}
    result = _build_content_blocks(text="hello", attachments=[att], protocol="openai-compatible")
    # Empty attachment → falls back to plain text since no valid attachment
    assert result == "hello" or (isinstance(result, list) and len([b for b in result if b.get("type") == "image_url"]) == 0)
