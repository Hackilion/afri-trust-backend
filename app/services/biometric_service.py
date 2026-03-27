"""Biometric verification service — face detection, liveness, and matching.

Uses pure OpenCV (no TensorFlow/DeepFace):
  - Face detection: Haar cascade classifier
  - Liveness: image-quality heuristics (blur, brightness, face ratio, color)
  - Face match: histogram comparison of detected face regions (correlation)
"""

import logging
from typing import Any
from uuid import UUID

import cv2
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.biometric import BiometricResult

logger = logging.getLogger(__name__)

FACE_CASCADE = None
PROFILE_CASCADE = None


def _get_cascades():
    global FACE_CASCADE, PROFILE_CASCADE
    if FACE_CASCADE is None:
        FACE_CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        PROFILE_CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_profileface.xml"
        )
    return FACE_CASCADE, PROFILE_CASCADE


def _detect_faces(image_path: str) -> list[tuple[int, int, int, int]]:
    img = cv2.imread(image_path)
    if img is None:
        return []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    frontal, profile = _get_cascades()

    faces = frontal.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
    if len(faces) == 0:
        faces = profile.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))

    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]


def _extract_face_region(image_path: str):
    img = cv2.imread(image_path)
    if img is None:
        return None
    faces = _detect_faces(image_path)
    if not faces:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    pad = int(min(w, h) * 0.1)
    ih, iw = img.shape[:2]
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(iw, x + w + pad)
    y2 = min(ih, y + h + pad)
    face_roi = img[y1:y2, x1:x2]
    return cv2.resize(face_roi, (128, 128))


def _compare_faces(face1: np.ndarray, face2: np.ndarray) -> float:
    """Compare two face ROIs using histogram correlation. Returns 0.0-1.0."""
    scores = []
    for ch in range(3):
        h1 = cv2.calcHist([face1], [ch], None, [64], [0, 256])
        h2 = cv2.calcHist([face2], [ch], None, [64], [0, 256])
        cv2.normalize(h1, h1)
        cv2.normalize(h2, h2)
        scores.append(cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL))
    return float(np.mean(scores))


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _liveness_check(image_path: str) -> dict[str, Any]:
    result: dict[str, Any] = {"checks": {}}

    img = cv2.imread(image_path)
    if img is None:
        result["passed"] = False
        result["score"] = 0.0
        result["checks"]["image_readable"] = False
        return result

    h, w = img.shape[:2]
    faces = _detect_faces(image_path)

    result["face_count"] = len(faces)
    result["checks"]["single_face"] = len(faces) == 1

    if faces:
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        area_ratio = (fw * fh) / (w * h)
        result["face_area_ratio"] = round(area_ratio, 4)
        result["checks"]["face_size_ok"] = 0.03 < area_ratio < 0.85
    else:
        result["face_area_ratio"] = 0.0
        result["checks"]["face_size_ok"] = False

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.Laplacian(gray, cv2.CV_64F).var()
    result["blur_score"] = round(float(blur), 2)
    result["checks"]["not_blurry"] = blur > 25

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    brightness = float(np.mean(hsv[:, :, 2]))
    saturation = float(np.mean(hsv[:, :, 1]))
    result["brightness"] = round(brightness, 1)
    result["saturation"] = round(saturation, 1)
    result["checks"]["good_brightness"] = 30 < brightness < 240
    result["checks"]["has_color"] = saturation > 8

    result["resolution"] = f"{w}x{h}"
    result["checks"]["adequate_resolution"] = w >= 200 and h >= 200

    passed = sum(1 for v in result["checks"].values() if v)
    total = len(result["checks"])
    result["score"] = round(passed / total, 2) if total else 0.0
    result["passed"] = result["score"] >= 0.6

    return _sanitize(result)


def _face_match(selfie_path: str, document_path: str) -> dict[str, Any]:
    face_selfie = _extract_face_region(selfie_path)
    face_doc = _extract_face_region(document_path)

    if face_selfie is None:
        return _sanitize({
            "passed": False, "score": 0.0,
            "reason": "No face detected in selfie",
            "model": "opencv-histogram",
        })
    if face_doc is None:
        return _sanitize({
            "passed": False, "score": 0.0,
            "reason": "No face detected in document",
            "model": "opencv-histogram",
        })

    similarity = _compare_faces(face_selfie, face_doc)
    similarity = max(0.0, min(1.0, similarity))

    return _sanitize({
        "passed": similarity >= 0.45,
        "score": round(similarity, 3),
        "threshold": 0.45,
        "model": "opencv-histogram",
    })


async def run_liveness_check(
    db: AsyncSession,
    *,
    session_id: UUID,
    step_progress_id: UUID,
    image_path: str,
) -> BiometricResult:
    result = _liveness_check(image_path)

    record = BiometricResult(
        session_id=session_id,
        step_progress_id=step_progress_id,
        check_type="liveness",
        passed=bool(result["passed"]),
        score=float(result.get("score", 0)),
        model_version="opencv-heuristic-v2",
        raw_response=result,
    )
    db.add(record)
    await db.flush()
    return record


async def run_face_match(
    db: AsyncSession,
    *,
    session_id: UUID,
    step_progress_id: UUID,
    selfie_path: str,
    document_face_path: str,
) -> BiometricResult:
    result = _face_match(selfie_path, document_face_path)

    record = BiometricResult(
        session_id=session_id,
        step_progress_id=step_progress_id,
        check_type="face_match",
        passed=bool(result["passed"]),
        score=float(result.get("score", 0)),
        model_version=str(result.get("model", "opencv-histogram")),
        raw_response=result,
    )
    db.add(record)
    await db.flush()
    return record
