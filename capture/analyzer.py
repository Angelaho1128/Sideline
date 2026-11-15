# =============================================================================
# capture/analyzer.py — Per-frame analysis: motion, scene cuts, OCR, pose
#
# What it does:
#   FrameAnalyzer processes each captured frame to extract metadata:
#   - Motion score via frame differencing (how much changed since last frame)
#   - Scene cut detection via histogram correlation
#   - Scoreboard OCR using pytesseract on a user-defined ROI
#   - YOLO pose estimation to identify on-field players and infer roles
#     (pitcher, batter, catcher) from body keypoint geometry
#   - Uniform color classification to distinguish teams using HSV hue
#     clustering, filtering out grass green and umpire black
#   - A debug renderer that stitches YOLO pose + motion heatmap side-by-side
#
# Technologies:
#   - OpenCV (cv2) for image processing, histograms, color conversion
#   - pytesseract for scoreboard text extraction (OCR)
#   - ultralytics YOLO (yolo11n-pose) for human pose estimation
#   - numpy for pixel math, array ops, k-means-style hue clustering
#
# Why it matters:
#   This module decides which frames are "interesting" — high motion, score
#   changes, camera cuts — so the key frame selector can pick the best ones
#   to send to Gemini. The OCR data feeds live game context into the prompt.
#   Pose and uniform detection power the debug dashboard for development.
# =============================================================================

import cv2
import numpy as np
try:
    import pytesseract
except ImportError:
    pytesseract = None
try:
    from ultralytics import YOLO
    _yolo_model = YOLO("yolo11n-pose.pt")
    _YOLO_AVAILABLE = True
    print("[yolo] Model loaded successfully")
except Exception as e:
    print(f"[yolo] Failed to load: {e}")
    _YOLO_AVAILABLE = False

# COCO pose keypoint indices
_L_SHOULDER = 5;  _R_SHOULDER = 6
_L_ELBOW    = 7;  _R_ELBOW    = 8
_L_WRIST    = 9;  _R_WRIST    = 10
_L_HIP      = 11; _R_HIP      = 12
_L_KNEE     = 13; _R_KNEE     = 14

# Role colors (BGR)
_ROLE_COLORS = {
    "pitcher": (0, 200, 255),   # yellow
    "batter":  (0, 100, 255),   # orange
    "catcher": (200, 0, 255),   # purple
    None:      (180, 180, 180), # grey
}

# Skeleton connections
_SKELETON = [
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
]

# ---------------------------------------------------------------------------
# Uniform color detection — auto-learns team colors from first N frames
# ---------------------------------------------------------------------------
_FIELD_GREEN_HSV_LOW  = np.array([35, 40, 40])   # HSV range for grass/turf
_FIELD_GREEN_HSV_HIGH = np.array([85, 255, 255])
_UMP_DARK_LOW         = np.array([0, 0, 0])       # umpire black
_UMP_DARK_HIGH        = np.array([180, 60, 60])


def _jersey_color(frame_bgr, x1, y1, x2, y2, kps):
    """
    Extract the dominant HSV hue of the jersey (torso region).
    Uses shoulder/hip keypoints to isolate the torso if available,
    otherwise falls back to the center third of the bounding box.
    Returns a mean HSV tuple or None.
    """
    # Torso crop: between shoulders and hips
    if kps is not None:
        l_sh = _kp(kps, _L_SHOULDER)
        r_sh = _kp(kps, _R_SHOULDER)
        l_hp = _kp(kps, _L_HIP)
        r_hp = _kp(kps, _R_HIP)
        if l_sh and r_sh and l_hp and r_hp:
            tx1 = int(min(l_sh[0], r_sh[0], l_hp[0], r_hp[0]))
            ty1 = int(min(l_sh[1], r_sh[1]))
            tx2 = int(max(l_sh[0], r_sh[0], l_hp[0], r_hp[0]))
            ty2 = int(max(l_hp[1], r_hp[1]))
            tx1, ty1 = max(0, tx1), max(0, ty1)
            tx2 = min(frame_bgr.shape[1], tx2)
            ty2 = min(frame_bgr.shape[0], ty2)
            if tx2 > tx1 + 5 and ty2 > ty1 + 5:
                crop = frame_bgr[ty1:ty2, tx1:tx2]
                return _dominant_hue(crop)

    # Fallback: center third of bounding box
    bw = x2 - x1
    bh = y2 - y1
    cx1 = x1 + bw // 3
    cx2 = x2 - bw // 3
    cy1 = y1 + bh // 4
    cy2 = y1 + (bh * 3) // 4
    cx1, cy1 = max(0, cx1), max(0, cy1)
    cx2 = min(frame_bgr.shape[1], cx2)
    cy2 = min(frame_bgr.shape[0], cy2)
    if cx2 > cx1 and cy2 > cy1:
        crop = frame_bgr[cy1:cy2, cx1:cx2]
        return _dominant_hue(crop)
    return None


def _dominant_hue(crop_bgr):
    """
    Returns the mean HSV of non-green, non-dark pixels in a crop.
    Filters out grass and shadow so we get the actual jersey color.
    """
    if crop_bgr.size == 0:
        return None
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)

    # Mask out field green and umpire black
    green_mask = cv2.inRange(hsv, _FIELD_GREEN_HSV_LOW, _FIELD_GREEN_HSV_HIGH)
    dark_mask  = cv2.inRange(hsv, _UMP_DARK_LOW, _UMP_DARK_HIGH)
    exclude    = cv2.bitwise_or(green_mask, dark_mask)
    jersey_mask = cv2.bitwise_not(exclude)

    pixels = hsv[jersey_mask > 0]
    if len(pixels) < 20:
        return None
    return tuple(np.mean(pixels, axis=0).astype(int))  # (H, S, V)


def _is_umpire(hsv_color):
    """Umpires wear dark/black — low value in HSV."""
    if hsv_color is None:
        return False
    return int(hsv_color[2]) < 60  # V < 60 = very dark


def _hue_distance(h1, h2):
    """Circular hue distance (0-180 in OpenCV HSV)."""
    d = abs(int(h1) - int(h2))
    return min(d, 180 - d)


class UniformClassifier:
    """
    Auto-detects two team colors from the first ~30 detections,
    then classifies each person as team_a, team_b, umpire, or crowd.
    """
    def __init__(self, learn_frames=30, hue_threshold=25):
        self.learn_frames   = learn_frames
        self.hue_threshold  = hue_threshold  # max hue distance to match a team
        self._samples       = []             # collected HSV tuples during learning
        self._team_a_hue    = None
        self._team_b_hue    = None
        self._learned       = False
        self._frames_seen   = 0

    def update_and_classify(self, hsv_color):
        """
        Feed a jersey HSV reading.
        Returns 'team_a', 'team_b', 'umpire', or None (crowd/unknown).
        """
        if hsv_color is None:
            return None

        if _is_umpire(hsv_color):
            return "umpire"

        if not self._learned:
            self._samples.append(hsv_color)
            self._frames_seen += 1
            if self._frames_seen >= self.learn_frames:
                self._fit()
            # During learning, classify against whatever we have so far
            if self._team_a_hue is None:
                return None

        return self._classify(hsv_color)

    def _fit(self):
        """2-cluster fit using vectorized numpy — no list comprehensions."""
        if len(self._samples) < 4:
            self._learned = True
            return
        try:
            hues = np.array([float(s[0]) for s in self._samples])
            print(f"[uniform] Fitting on hues: {hues}")

            c1, c2 = float(hues.min()), float(hues.max())

            for _ in range(10):
                d1 = np.minimum(np.abs(hues - c1), 180 - np.abs(hues - c1))
                d2 = np.minimum(np.abs(hues - c2), 180 - np.abs(hues - c2))
                mask1 = d1 <= d2
                mask2 = ~mask1
                new_c1 = float(np.mean(hues[mask1])) if mask1.any() else c1
                new_c2 = float(np.mean(hues[mask2])) if mask2.any() else c2
                if abs(new_c1 - c1) < 0.5 and abs(new_c2 - c2) < 0.5:
                    break
                c1, c2 = new_c1, new_c2

            self._team_a_hue = c1
            self._team_b_hue = c2
            self._learned    = True
            print(f"[uniform] Team A hue: {c1:.0f}  Team B hue: {c2:.0f}")
        except Exception as e:
            print(f"[uniform] Fit failed: {e} — using defaults")
            self._team_a_hue = 0.0
            self._team_b_hue = 90.0
            self._learned    = True


    def _classify(self, hsv_color):
        h = int(hsv_color[0])
        s = int(hsv_color[1])

        # Low saturation = white/grey jersey (often home team or crowd)
        # Still assign to nearest team hue
        da = _hue_distance(h, self._team_a_hue)
        db = _hue_distance(h, self._team_b_hue)

        if min(da, db) > self.hue_threshold and s < 40:
            return None  # probably crowd or indeterminate

        return "team_a" if da <= db else "team_b"

    @property
    def learned(self):
        return self._learned


# ---------------------------------------------------------------------------
# Module-level uniform classifier (shared across frames)
# ---------------------------------------------------------------------------
_uniform_clf = UniformClassifier()

# Team display colors (BGR) — assigned once teams are learned
_TEAM_COLORS = {
    "team_a":  (255, 180, 0),   # blue
    "team_b":  (0, 180, 255),   # orange
    "umpire":  (128, 128, 128), # grey
    None:      (60, 60, 60),    # dark grey = crowd/unknown
}


def _kp(keypoints, idx):
    """Return (x, y) for a keypoint if confidence > 0.15, else None."""
    if keypoints is None or idx >= len(keypoints):
        return None
    x, y, conf = float(keypoints[idx][0]), float(keypoints[idx][1]), float(keypoints[idx][2])
    return (x, y) if conf > 0.15 else None


def _infer_role_from_pose(keypoints, box_h):
    l_shoulder = _kp(keypoints, _L_SHOULDER)
    r_shoulder = _kp(keypoints, _R_SHOULDER)
    l_wrist    = _kp(keypoints, _L_WRIST)
    r_wrist    = _kp(keypoints, _R_WRIST)
    l_hip      = _kp(keypoints, _L_HIP)
    r_hip      = _kp(keypoints, _R_HIP)
    l_knee     = _kp(keypoints, _L_KNEE)
    r_knee     = _kp(keypoints, _R_KNEE)

    if l_hip and r_hip and l_knee and r_knee:
        hip_y  = (l_hip[1]  + r_hip[1])  / 2
        knee_y = (l_knee[1] + r_knee[1]) / 2
        if abs(knee_y - hip_y) / (box_h + 1e-6) < 0.18:
            return "catcher"

    if l_shoulder and r_shoulder:
        shoulder_y        = (l_shoulder[1] + r_shoulder[1]) / 2
        shoulder_x_spread = abs(r_shoulder[0] - l_shoulder[0])
    elif l_shoulder:
        shoulder_y, shoulder_x_spread = l_shoulder[1], 0
    elif r_shoulder:
        shoulder_y, shoulder_x_spread = r_shoulder[1], 0
    else:
        return None

    l_above = l_wrist and l_wrist[1] < shoulder_y
    r_above = r_wrist and r_wrist[1] < shoulder_y

    if l_above and r_above and l_wrist and r_wrist:
        wrist_spread = abs(r_wrist[0] - l_wrist[0])
        if wrist_spread > shoulder_x_spread * 0.8:
            return "batter"

    if l_above or r_above:
        raised = l_wrist if l_above else r_wrist
        raise_amount = (shoulder_y - raised[1]) / (box_h + 1e-6)
        if raise_amount > 0.10:
            return "pitcher"

    return None


class FrameAnalyzer:
    def __init__(self, scoreboard_roi=None):
        self.scoreboard_roi = scoreboard_roi
        self.prev_gray = None
        self.prev_scoreboard = None
        self._has_prev_gray = False
        self._has_prev_scoreboard = False
        self.last_diff = None
        self.last_motion = 0.0
        self.frame_count = 0
        self.last_ocr_text = ""
        self.last_frame = None

    # ------------------------------------------------------------------
    # Debug rendering
    # ------------------------------------------------------------------
    def render_debug(self, frame):
        if self.last_diff is None:
            return None
        frame_h, frame_w = frame.shape[:2]
        if frame_h == 0 or frame_w == 0:
            return None

        # ---- Left panel: YOLO pose + uniform classification ----
        left = frame.copy()

        if _YOLO_AVAILABLE:
            results = _yolo_model(left, verbose=False)[0]
            boxes   = results.boxes
            kps_all = results.keypoints

            for i, box in enumerate(boxes):
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf  = float(box.conf[0])
                box_h = y2 - y1

                kps = None
                if kps_all is not None and i < len(kps_all.data):
                    kps = kps_all.data[i].cpu().numpy()

                # Skip anyone in the top 40% of the frame — that's the stands
                box_center_y = (y1 + y2) / 2 / frame_h
                if box_center_y < 0.40:
                    continue

                # Also skip very small boxes — distant crowd, not field players
                if box_h < frame_h * 0.10:
                    continue

                # Uniform color classification
                hsv   = _jersey_color(frame, x1, y1, x2, y2, kps)
                team  = _uniform_clf.update_and_classify(hsv)

                # Pose-based role (only meaningful for on-field players)
                role  = _infer_role_from_pose(kps, box_h) if team in ("team_a", "team_b") else None

                # Skip crowd/unknown to reduce noise
                if team is None:
                    continue

                # Color: use role color if we have a role, else team color
                color = _ROLE_COLORS.get(role) if role else _TEAM_COLORS.get(team, (180, 180, 180))

                kp_count = sum(1 for j in range(17) if _kp(kps, j)) if kps is not None else 0
                team_label = team or "?"
                role_label = role or ""
                label = f"{team_label} {role_label} {conf:.2f} kp:{kp_count}".strip()

                cv2.rectangle(left, (x1, y1), (x2, y2), color, 2)
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                cv2.rectangle(left, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
                cv2.putText(left, label, (x1 + 2, y1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

                if kps is not None:
                    for a, b in _SKELETON:
                        pa, pb = _kp(kps, a), _kp(kps, b)
                        if pa and pb:
                            cv2.line(left,
                                     (int(pa[0]), int(pa[1])),
                                     (int(pb[0]), int(pb[1])),
                                     color, 1)
                    for idx in range(len(kps)):
                        pt = _kp(kps, idx)
                        if pt:
                            cv2.circle(left, (int(pt[0]), int(pt[1])), 3, color, -1)

        status = "learning uniforms..." if not _uniform_clf.learned else "uniforms learned"
        cv2.putText(left, f"YOLO pose + uniforms ({status})", (10, frame_h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # ---- Right panel: OpenCV motion analysis ----
        right = frame.copy()

        if self.scoreboard_roi:
            x, y, w, h = self.scoreboard_roi
            cv2.rectangle(right, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(right, "scoreboard ROI", (x, max(y - 6, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        diff_colored = cv2.applyColorMap(self.last_diff, cv2.COLORMAP_HOT)
        if diff_colored.shape[:2] != right.shape[:2]:
            diff_colored = cv2.resize(diff_colored, (right.shape[1], right.shape[0]))
        right = cv2.addWeighted(right, 0.65, diff_colored, 0.35, 0)

        cv2.putText(right, f"Motion: {self.last_motion:.1f}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        cv2.putText(right, f"Frames: {self.frame_count}", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        if self.last_ocr_text:
            cv2.putText(right, f"OCR: {self.last_ocr_text[:40]}", (10, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.putText(right, "OpenCV — motion analysis", (10, frame_h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

        # ---- Stitch panels ----
        target_h = 480
        scale    = target_h / frame_h
        target_w = int(frame_w * scale)
        left  = cv2.resize(left,  (target_w, target_h))
        right = cv2.resize(right, (target_w, target_h))
        divider = np.zeros((target_h, 4, 3), dtype=np.uint8)
        divider[:] = (60, 60, 60)
        return np.hstack([left, divider, right])

    # ------------------------------------------------------------------
    # Core frame analysis
    # ------------------------------------------------------------------
    def analyze(self, frame):
        if frame.size == 0:
            return {
                "motion_score": 0.0,
                "is_scene_cut": False,
                "score_changed": False,
                "ocr_text": self.last_ocr_text,
            }
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        metadata = {
            "motion_score": 0.0,
            "is_scene_cut": False,
            "score_changed": False,
            "ocr_text": self.last_ocr_text,
        }
        if self._has_prev_gray:
            if self.prev_gray.shape != gray.shape:
                self.prev_gray = gray.copy()
                self.last_diff = np.zeros_like(gray)
                self._has_prev_gray = True
                self.frame_count += 1
                return metadata
            diff = cv2.absdiff(self.prev_gray, gray)
            self.last_diff = diff.copy()
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            metadata["motion_score"] = float(np.mean(thresh))
            self.last_motion = metadata["motion_score"]
            hist_prev = cv2.calcHist([self.prev_gray], [0], None, [256], [0, 256])
            hist_curr = cv2.calcHist([gray], [0], None, [256], [0, 256])
            cv2.normalize(hist_prev, hist_prev)
            cv2.normalize(hist_curr, hist_curr)
            correlation = cv2.compareHist(hist_prev, hist_curr, cv2.HISTCMP_CORREL)
            metadata["is_scene_cut"] = correlation < 0.5
        else:
            self.last_diff = np.zeros_like(gray)

        if self.scoreboard_roi:
            x, y, w, h = self.scoreboard_roi
            frame_h, frame_w = gray.shape[:2]
            if y + h <= frame_h and x + w <= frame_w:
                scoreboard_crop = gray[y : y + h, x : x + w]
                if (
                    self._has_prev_scoreboard
                    and scoreboard_crop.shape == self.prev_scoreboard.shape
                ):
                    sb_diff = cv2.absdiff(self.prev_scoreboard, scoreboard_crop)
                    metadata["score_changed"] = float(np.mean(sb_diff)) > 15
                self.prev_scoreboard = scoreboard_crop.copy()
                self._has_prev_scoreboard = True
                if self.frame_count % 6 == 0 and pytesseract is not None:
                    try:
                        _, sb_thresh = cv2.threshold(
                            scoreboard_crop, 150, 255, cv2.THRESH_BINARY
                        )
                        sb_upscaled = cv2.resize(
                            sb_thresh, None, fx=2, fy=2,
                            interpolation=cv2.INTER_CUBIC,
                        )
                        text = pytesseract.image_to_string(
                            sb_upscaled, config="--psm 6"
                        ).strip()
                        if text:
                            self.last_ocr_text = text
                            metadata["ocr_text"] = text
                    except Exception:
                        pass

        self.prev_gray = gray.copy()
        self._has_prev_gray = True
        self.frame_count += 1
        self.last_frame = frame
        return metadata