"""Biometric verification service — face detection, liveness, and matching.

Uses pure OpenCV:
  - Face detection: Haar cascade (frontal + profile)
  - Liveness: image-quality heuristics (blur, brightness, face ratio, color, texture)
  - Face match: ORB keypoint feature matching + structural similarity (SSIM)
    on extracted face regions — NOT histogram (which only compares colors)
"""

import logging
from typing import Any, Optional
from uuid import UUID

import cv2
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.biometric import BiometricResult
from app.services import vision_openrouter

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
    gray = cv2.equalizeHist(gray)
    frontal, profile = _get_cascades()

    faces = frontal.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60)
    )
    if len(faces) == 0:
        faces = profile.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60)
        )
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]


def _extract_face_region(image_path: str, size: int = 160):
    """Extract the largest face region, resize to a fixed square."""
    img = cv2.imread(image_path)
    if img is None:
        return None
    faces = _detect_faces(image_path)
    if not faces:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    pad = int(min(w, h) * 0.15)
    ih, iw = img.shape[:2]
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(iw, x + w + pad)
    y2 = min(ih, y + h + pad)
    face_roi = img[y1:y2, x1:x2]
    return cv2.resize(face_roi, (size, size))


def _ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """Compute structural similarity index between two grayscale images."""
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    g1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY).astype(np.float64)
    g2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY).astype(np.float64)

    mu1 = cv2.GaussianBlur(g1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(g2, (11, 11), 1.5)

    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.GaussianBlur(g1 ** 2, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(g2 ** 2, (11, 11), 1.5) - mu2_sq
    sigma12 = cv2.GaussianBlur(g1 * g2, (11, 11), 1.5) - mu1_mu2

    numerator = (2 * mu1_mu2 + C1) * (2 * sigma12 + C2)
    denominator = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)

    ssim_map = numerator / denominator
    return float(np.mean(ssim_map))


def _orb_match_score(face1: np.ndarray, face2: np.ndarray) -> float:
    """Match faces using ORB keypoints. Returns 0.0-1.0."""
    g1 = cv2.cvtColor(face1, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(face2, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=500)
    kp1, des1 = orb.detectAndCompute(g1, None)
    kp2, des2 = orb.detectAndCompute(g2, None)

    if des1 is None or des2 is None or len(kp1) < 5 or len(kp2) < 5:
        return 0.0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    good = []
    for pair in matches:
        if len(pair) == 2:
            m, n = pair
            if m.distance < 0.75 * n.distance:
                good.append(m)

    max_possible = min(len(kp1), len(kp2))
    if max_possible == 0:
        return 0.0

    ratio = len(good) / max_possible
    return min(1.0, ratio * 2.5)


def _compare_faces(face1: np.ndarray, face2: np.ndarray) -> dict[str, float]:
    """Multi-method face comparison. Returns individual and combined scores."""
    ssim_score = _ssim(face1, face2)
    ssim_normalized = max(0.0, (ssim_score - 0.2) / 0.6)

    orb_score = _orb_match_score(face1, face2)

    combined = (ssim_normalized * 0.5) + (orb_score * 0.5)
    combined = max(0.0, min(1.0, combined))

    return {
        "ssim": round(ssim_score, 3),
        "orb_feature_match": round(orb_score, 3),
        "combined": round(combined, 3),
    }


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

    if faces:
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        face_gray = gray[fy:fy+fh, fx:fx+fw]
        if face_gray.size > 0:
            texture = cv2.Laplacian(face_gray, cv2.CV_64F).var()
            result["face_texture"] = round(float(texture), 2)
            result["checks"]["face_has_texture"] = texture > 15
        else:
            result["checks"]["face_has_texture"] = False
    else:
        result["checks"]["face_has_texture"] = False

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
            "passed": False,
            "score": 0.0,
            "reason": "No face detected in selfie",
            "model": "opencv-orb-ssim-v2",
        })
    if face_doc is None:
        return _sanitize({
            "passed": False,
            "score": 0.0,
            "reason": "No face detected in document",
            "model": "opencv-orb-ssim-v2",
        })

    scores = _compare_faces(face_selfie, face_doc)
    combined = scores["combined"]
    threshold = 0.35

    return _sanitize({
        "passed": combined >= threshold,
        "score": combined,
        "threshold": threshold,
        "ssim_score": scores["ssim"],
        "orb_feature_score": scores["orb_feature_match"],
        "model": "opencv-orb-ssim-v2",
    })


async def run_liveness_check(
    db: AsyncSession,
    *,
    session_id: UUID,
    step_progress_id: UUID,
    image_path: str,
) -> BiometricResult:
    opencv_result = _liveness_check(image_path)
    combined: dict[str, Any] = {"opencv": opencv_result}
    passed = bool(opencv_result["passed"])
    score = float(opencv_result.get("score", 0))
    model_version = "opencv-heuristic-v2"

    if (settings.OPENROUTER_API_KEY or "").strip():
        try:
            with open(image_path, "rb") as f:
                raw = f.read()
            mime, _ = mimetypes.guess_type(image_path)
            mime = mime or "image/jpeg"
            vout = await vision_openrouter.assess_selfie_liveness_vision(raw, mime)
            if vout and isinstance(vout.get("live_likely"), bool):
                combined["vision"] = vout
                vconf = float(vout.get("confidence") or 0)
                vlive = bool(vout["live_likely"])
                passed = vlive and vconf >= 0.5
                score = round(max(0.0, min(1.0, vconf)), 3)
                model_version = f"{vision_openrouter.vision_model_name()}+opencv"
        except Exception as e:
            logger.warning("OpenRouter liveness vision failed, using OpenCV only: %s", e)

    record = BiometricResult(
        session_id=session_id,
        step_progress_id=step_progress_id,
        check_type="liveness",
        passed=bool(result["passed"]),
        score=float(result.get("score", 0)),
        model_version="opencv-heuristic-v3",
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
        model_version=str(result.get("model", "opencv-orb-ssim-v2")),
        raw_response=result,
    )
    db.add(record)
    await db.flush()
    return record
