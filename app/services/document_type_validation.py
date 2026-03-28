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
