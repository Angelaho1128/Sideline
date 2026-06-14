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

# Skeleton connections to draw (pairs of keypoint indices)
_SKELETON = [
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),   # shoulders + arms
    (5, 11), (6, 12), (11, 12),                  # torso
    (11, 13), (13, 15), (12, 14), (14, 16),      # legs
]


def _kp(keypoints, idx):
    """Return (x, y) for a keypoint if confidence > 0.15, else None."""
    if keypoints is None or idx >= len(keypoints):
        return None
    x, y, conf = float(keypoints[idx][0]), float(keypoints[idx][1]), float(keypoints[idx][2])
    return (x, y) if conf > 0.15 else None  # lowered from 0.3 for small figures


def _infer_role_from_pose(keypoints, box_h):
    """
    Infer baseball role from body pose keypoints.

    Catcher  — deep squat: knees at nearly the same vertical level as hips
    Batter   — both wrists raised above shoulders AND spread wider than shoulder width
    Pitcher  — one wrist significantly above shoulder level (throwing arm)
    """
    l_shoulder = _kp(keypoints, _L_SHOULDER)
    r_shoulder = _kp(keypoints, _R_SHOULDER)
    l_wrist    = _kp(keypoints, _L_WRIST)
    r_wrist    = _kp(keypoints, _R_WRIST)
    l_hip      = _kp(keypoints, _L_HIP)
    r_hip      = _kp(keypoints, _R_HIP)
    l_knee     = _kp(keypoints, _L_KNEE)
    r_knee     = _kp(keypoints, _R_KNEE)

    # --- Catcher: crouching — knees close to hips vertically ---
    if l_hip and r_hip and l_knee and r_knee:
        hip_y  = (l_hip[1]  + r_hip[1])  / 2
        knee_y = (l_knee[1] + r_knee[1]) / 2
        if abs(knee_y - hip_y) / (box_h + 1e-6) < 0.18:
            return "catcher"

    # Shoulder reference for wrist comparisons
    if l_shoulder and r_shoulder:
        shoulder_y       = (l_shoulder[1] + r_shoulder[1]) / 2
        shoulder_x_spread = abs(r_shoulder[0] - l_shoulder[0])
    elif l_shoulder:
        shoulder_y, shoulder_x_spread = l_shoulder[1], 0
    elif r_shoulder:
        shoulder_y, shoulder_x_spread = r_shoulder[1], 0
    else:
        return None

    l_above = l_wrist and l_wrist[1] < shoulder_y
    r_above = r_wrist and r_wrist[1] < shoulder_y

    # --- Batter: both wrists above shoulders, arms spread wide ---
    if l_above and r_above and l_wrist and r_wrist:
        wrist_spread = abs(r_wrist[0] - l_wrist[0])
        if wrist_spread > shoulder_x_spread * 0.8:
            return "batter"

    # --- Pitcher: one wrist well above shoulder (throwing motion) ---
    if l_above or r_above:
        raised = l_wrist if l_above else r_wrist
        raise_amount = (shoulder_y - raised[1]) / (box_h + 1e-6)
        if raise_amount > 0.10:  # lowered from 0.12
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
        self.last_frame = None  # latest frame for main-thread debug display

    # ------------------------------------------------------------------
    # Debug rendering — returns a BGR numpy image (display is caller's job)
    # ------------------------------------------------------------------
    def render_debug(self, frame):
        """Render the debug dashboard as a BGR numpy array.

        Returns None if there's nothing to show yet.
        """
        if self.last_diff is None:
            return None

        frame_h, frame_w = frame.shape[:2]
        if frame_h == 0 or frame_w == 0:
            return None

        # ---- Left panel: YOLO pose-based role detection ----
        left = frame.copy()

        if _YOLO_AVAILABLE:
            results = _yolo_model(left, verbose=False)[0]
            boxes   = results.boxes
            kps_all = results.keypoints  # (N, 17, 3)

            for i, box in enumerate(boxes):
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf  = float(box.conf[0])
                box_h = y2 - y1

                kps = None
                if kps_all is not None and i < len(kps_all.data):
                    kps = kps_all.data[i].cpu().numpy()  # (17, 3)

                role  = _infer_role_from_pose(kps, box_h)
                color = _ROLE_COLORS[role]

                kp_count = sum(1 for j in range(17) if _kp(kps, j)) if kps is not None else 0
                label = f"{role or 'person'} {conf:.2f} kp:{kp_count}"

                cv2.rectangle(left, (x1, y1), (x2, y2), color, 2)

                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(left, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
                cv2.putText(left, label, (x1 + 2, y1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

                if kps is not None:
                    for a, b in _SKELETON:
                        pa = _kp(kps, a)
                        pb = _kp(kps, b)
                        if pa and pb:
                            cv2.line(left,
                                     (int(pa[0]), int(pa[1])),
                                     (int(pb[0]), int(pb[1])),
                                     color, 1)
                    for idx in range(len(kps)):
                        pt = _kp(kps, idx)
                        if pt:
                            cv2.circle(left, (int(pt[0]), int(pt[1])), 3, color, -1)

        cv2.putText(left, "YOLO pose — baseball roles", (10, frame_h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

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

        # ---- Stitch panels side by side ----
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