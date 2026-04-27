"""
OCR pipeline for scanned municipality diarium PDFs.
Uses Gemini Vision. Runs only on PDFs where pdf_text IS NULL.
"""
import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)


async def extract_pdf_text(pdf_url: str) -> dict:
    """
    Download PDF, send to Gemini Vision, return structured fields.
    Returns: {case_id, title, handling_unit, filed_at, full_text}
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    async with httpx.AsyncClient(timeout=60) as client:
        pdf_resp = await client.get(pdf_url)
        pdf_resp.raise_for_status()
        pdf_bytes = pdf_resp.content

    import base64
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()

    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash-preview-05-20")

    prompt = """
    This is a scanned Swedish municipality diarium document.
    Extract the following fields in JSON format:
    - case_id: the diarienummer/case reference
    - title: the case title/rubrik
    - handling_unit: the responsible department/handläggningsenhet
    - filed_at: the date received in YYYY-MM-DD format (null if not found)
    - full_text: the complete text content of the document

    Respond ONLY with valid JSON, no other text.
    """

    response = model.generate_content(
        [
            {"mime_type": "application/pdf", "data": pdf_b64},
            prompt,
        ]
    )

    import json
    try:
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as exc:
        log.warning("failed to parse Gemini OCR response: %s", exc)
        return {
            "case_id": None,
            "title": None,
            "handling_unit": None,
            "filed_at": None,
            "full_text": response.text,
        }
