"""Compare user-declared document type with OCR/vision classification after upload."""

from app.models.document import ExtractedIdentity

GOV_ID_TYPES = frozenset(
    {
        "passport",
        "national_id",
        "drivers_license",
        "voter_card",
        "residence_permit",
    }
)


def evaluate_declared_vs_extracted(
    declared: str,
    extracted: ExtractedIdentity,
) -> tuple[bool, str | None]:
    """
    Returns (ok, error_message). When ok is False, the upload should be rejected
    and the artifact should not count toward the verification check.
    """
    ed = extracted.extracted_data or {}
    if ed.get("error"):
        err = ed.get("error")
        return False, err if isinstance(err, str) else "Document could not be processed. Try a clearer photo."

    detected = (extracted.document_classification or "other").strip().lower()
    declared_n = (declared or "").strip().lower()

    if declared_n == "other":
        return True, None

    if detected == declared_n:
        return True, None

    if detected == "other":
        # Inconclusive classification — do not block the user.
        return True, None

    if declared_n == "address_proof":
        if detected == "address_proof":
            return True, None
        if detected in GOV_ID_TYPES:
            return False, (
                "You chose address proof, but this image looks like a government-issued ID. "
                "Please upload a utility bill, bank statement, or official letter that shows your address."
            )
        return True, None

    if declared_n in GOV_ID_TYPES and detected in GOV_ID_TYPES:
        pretty_d = detected.replace("_", " ")
        pretty_decl = declared_n.replace("_", " ")
        return False, (
            f"You selected {pretty_decl}, but the image looks like a {pretty_d}. "
            "Pick the matching document type or upload the correct document."
        )

    if declared_n in GOV_ID_TYPES and detected == "address_proof":
        return False, (
            f"You selected {declared_n.replace('_', ' ')}, but this image looks like address or correspondence "
            "rather than a government ID. Please upload your ID document."
        )

    pretty_d = detected.replace("_", " ")
    pretty_decl = declared_n.replace("_", " ")
    return False, (
        f"The image does not match the selected type ({pretty_decl}). "
        f"It was classified as {pretty_d}. Correct the type or upload a different file."
    )


def _non_empty(val: object | None) -> bool:
    if val is None:
        return False
    return len(str(val).strip()) > 0


def evaluate_document_quality(
    declared: str,
    extracted: ExtractedIdentity,
) -> tuple[bool, str | None]:
    """Reject unreadable or empty extractions after type match."""
    fs = extracted.fraud_signals or {}
    if fs.get("processing_error"):
        return False, "Document processing failed. Try another photo or file format."

    if fs.get("likely_blurry") and fs.get("low_resolution"):
        return False, (
            "This image is too blurry and too small. Use a sharper photo "
            "and ensure the full document is visible."
        )

    qs = fs.get("quality_score")
    if isinstance(qs, (int, float)) and float(qs) < 0.25:
        return False, "Image quality is too low. Retake with better lighting and focus."

    ed = extracted.extracted_data or {}
    declared_n = (declared or "").strip().lower()
    vision = bool(ed.get("vision_extraction"))
    conf = float(extracted.confidence_score or 0)

    if declared_n in GOV_ID_TYPES:
        has_core = (
            _non_empty(ed.get("document_number"))
            or _non_empty(ed.get("full_name"))
            or (_non_empty(ed.get("given_name")) and _non_empty(ed.get("family_name")))
        )
        if vision and not has_core and conf < 0.22:
            return False, (
                "We could not read your name or document number clearly. "
                "Retake the photo with the ID flat and well lit."
            )

    if declared_n == "address_proof":
        addr = ed.get("address_line")
        if vision and (not addr or len(str(addr).strip()) < 10):
            return False, (
                "We could not read a full street address. Upload a recent utility bill, "
                "bank statement, or official letter showing your address."
            )

    return True, None
