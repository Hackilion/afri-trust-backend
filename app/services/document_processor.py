"""Real document processing service — OCR + classification + fraud signals.

Uses pytesseract (Tesseract OCR) for text extraction and Pillow for image
analysis. Extracts structured identity fields from documents, classifies
document types, and computes basic fraud-detection heuristics.
"""

import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

from PIL import Image, ImageFilter, ImageStat
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentArtifact, ExtractedIdentity

logger = logging.getLogger(__name__)

try:
    import pytesseract

    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not installed — OCR will return empty results")


DATE_PATTERNS = [
    re.compile(r"\b(\d{2})[/\-.](\d{2})[/\-.](\d{4})\b"),
    re.compile(r"\b(\d{4})[/\-.](\d{2})[/\-.](\d{2})\b"),
]
ID_NUMBER_PATTERN = re.compile(r"\b[A-Z]{0,3}\d{5,15}\b")
NAME_LINE_PATTERN = re.compile(
    r"(?:name|nom|surname|given|first|last|prenom)[:\s]*([A-Za-z\s\-']{2,50})",
    re.IGNORECASE,
)
DOB_LABEL_PATTERN = re.compile(
    r"(?:date.of.birth|dob|born|naissance|birth)[:\s]*([\d/\-.\s]+)",
    re.IGNORECASE,
)
NATIONALITY_PATTERN = re.compile(
    r"(?:nationality|nationalite|citizenship)[:\s]*([A-Za-z\s]{2,30})",
    re.IGNORECASE,
)
SEX_PATTERN = re.compile(
    r"(?:sex|genre|gender)[:\s]*(M|F|male|female|MALE|FEMALE)",
    re.IGNORECASE,
)
MRZ_LINE = re.compile(r"[A-Z0-9<]{30,44}")

DOC_KEYWORDS = {
    "passport": ["passport", "passeport", "travel document"],
    "national_id": [
        "national",
        "identity",
        "identite",
        "carte",
        "kebele",
        "id card",
    ],
    "drivers_license": ["driver", "licence", "license", "permis", "conduire"],
    "voter_card": ["voter", "electoral", "election"],
    "residence_permit": ["residence", "permit", "sejour"],
}


def _classify_document(text: str) -> str:
    lower = text.lower()
    scores = {}
    for doc_type, keywords in DOC_KEYWORDS.items():
        scores[doc_type] = sum(1 for kw in keywords if kw in lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def _extract_fields(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}

    for m in NAME_LINE_PATTERN.finditer(text):
        name = m.group(1).strip()
        if len(name) > 2:
            fields.setdefault("full_name", name)
            break

    dob_match = DOB_LABEL_PATTERN.search(text)
    if dob_match:
        raw_date = dob_match.group(1).strip()
        for dp in DATE_PATTERNS:
            dm = dp.search(raw_date)
            if dm:
                groups = dm.groups()
                if len(groups[0]) == 4:
                    fields["date_of_birth"] = f"{groups[0]}-{groups[1]}-{groups[2]}"
                else:
                    fields["date_of_birth"] = f"{groups[2]}-{groups[1]}-{groups[0]}"
                break

    id_matches = ID_NUMBER_PATTERN.findall(text)
    if id_matches:
        fields["id_number"] = max(id_matches, key=len)

    nat_match = NATIONALITY_PATTERN.search(text)
    if nat_match:
        fields["nationality"] = nat_match.group(1).strip()

    sex_match = SEX_PATTERN.search(text)
    if sex_match:
        val = sex_match.group(1).upper()
        fields["gender"] = "male" if val.startswith("M") else "female"

    mrz_lines = MRZ_LINE.findall(text.replace(" ", ""))
    if len(mrz_lines) >= 2:
        fields["mrz_detected"] = True
        mrz = mrz_lines[-1]
        if len(mrz) >= 28:
            raw_dob = mrz[13:19]
            try:
                dob_parsed = datetime.strptime(raw_dob, "%y%m%d")
                fields.setdefault(
                    "date_of_birth", dob_parsed.strftime("%Y-%m-%d")
                )
            except ValueError:
                pass

    dates = []
    for dp in DATE_PATTERNS:
        for dm in dp.finditer(text):
            dates.append(dm.group(0))
    if dates:
        fields["dates_found"] = dates

    return fields


def _compute_fraud_signals(img: Image.Image, text: str) -> dict[str, Any]:
    signals: dict[str, Any] = {}

    stat = ImageStat.Stat(img.convert("L"))
    signals["brightness_mean"] = round(stat.mean[0], 1)
    signals["brightness_stddev"] = round(stat.stddev[0], 1)

    w, h = img.size
    signals["resolution"] = f"{w}x{h}"
    signals["low_resolution"] = w < 400 or h < 300

    edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    sharpness = edge_stat.mean[0]
    signals["sharpness_score"] = round(sharpness, 2)
    signals["likely_blurry"] = sharpness < 10

    text_len = len(text.strip())
    signals["text_length"] = text_len
    signals["too_little_text"] = text_len < 20

    signals["tamper_detected"] = False
    if signals["low_resolution"] and signals["likely_blurry"]:
        signals["quality_warning"] = True
    else:
        signals["quality_warning"] = False

    quality = 1.0
    if signals["low_resolution"]:
        quality -= 0.2
    if signals["likely_blurry"]:
        quality -= 0.3
    if signals["too_little_text"]:
        quality -= 0.2
    signals["quality_score"] = round(max(quality, 0.0), 2)

    return signals


async def process_document(
    db: AsyncSession,
    artifact: DocumentArtifact,
    file_path: str,
) -> ExtractedIdentity:
    raw_text = ""
    confidence = 0.0
    fraud_signals: dict[str, Any] = {}
    doc_classification = artifact.document_type
    extracted_data: dict[str, Any] = {}

    try:
        img = Image.open(file_path)

        if TESSERACT_AVAILABLE:
            ocr_data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT, lang="eng"
            )
            confidences = [
                int(c)
                for c in ocr_data.get("conf", [])
                if str(c).lstrip("-").isdigit() and int(c) > 0
            ]
            confidence = round(sum(confidences) / len(confidences) / 100, 2) if confidences else 0.0

            raw_text = pytesseract.image_to_string(img, lang="eng")
        else:
            raw_text = ""
            confidence = 0.0

        doc_classification = _classify_document(raw_text)
        extracted_data = _extract_fields(raw_text)
        extracted_data["raw_text_preview"] = raw_text[:500]
        fraud_signals = _compute_fraud_signals(img, raw_text)

    except Exception:
        logger.exception("Document processing failed for %s", artifact.id)
        confidence = 0.0
        extracted_data = {"error": "Processing failed"}
        fraud_signals = {"processing_error": True}

    extracted = ExtractedIdentity(
        document_artifact_id=artifact.id,
        extracted_data=extracted_data,
        confidence_score=confidence,
        document_classification=doc_classification,
        fraud_signals=fraud_signals,
    )
    db.add(extracted)
    await db.flush()
    return extracted
