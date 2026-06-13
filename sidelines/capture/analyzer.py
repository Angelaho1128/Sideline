import cv2
import numpy as np

try:
    import pytesseract
except ImportError:
    pytesseract = None


class FrameAnalyzer:
    def __init__(self, scoreboard_roi=None):
        self.scoreboard_roi = scoreboard_roi  # (x, y, w, h)
        self.prev_gray = None
        self.prev_scoreboard = None
        self.last_diff = None
        self.frame_count = 0
        self.last_ocr_text = ""

    def analyze(self, frame):
        """Analyze a frame and return metadata dict."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        metadata = {
            "motion_score": 0.0,
            "is_scene_cut": False,
            "score_changed": False,
            "ocr_text": self.last_ocr_text,
        }

        if self.prev_gray is not None and self.prev_gray.shape == gray.shape:
            # 1. Frame differencing for motion score
            diff = cv2.absdiff(self.prev_gray, gray)
            self.last_diff = diff.copy()
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            metadata["motion_score"] = float(np.mean(thresh))

            # 2. Histogram comparison for scene cuts
            hist_prev = cv2.calcHist([self.prev_gray], [0], None, [256], [0, 256])
            hist_curr = cv2.calcHist([gray], [0], None, [256], [0, 256])
            cv2.normalize(hist_prev, hist_prev)
            cv2.normalize(hist_curr, hist_curr)
            correlation = cv2.compareHist(
                hist_prev, hist_curr, cv2.HISTCMP_CORREL
            )
            metadata["is_scene_cut"] = correlation < 0.5
        else:
            self.last_diff = np.zeros_like(gray)

        # 3. Scoreboard ROI analysis
        if self.scoreboard_roi:
            x, y, w, h = self.scoreboard_roi
            # Bounds check
            frame_h, frame_w = gray.shape[:2]
            if y + h <= frame_h and x + w <= frame_w:
                scoreboard_crop = gray[y : y + h, x : x + w]

                if (
                    self.prev_scoreboard is not None
                    and scoreboard_crop.shape == self.prev_scoreboard.shape
                ):
                    sb_diff = cv2.absdiff(self.prev_scoreboard, scoreboard_crop)
                    metadata["score_changed"] = float(np.mean(sb_diff)) > 15

                self.prev_scoreboard = scoreboard_crop.copy()

                # 4. OCR every 6th frame (~every 2 sec at 3fps)
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
        self.frame_count += 1
        return metadata
