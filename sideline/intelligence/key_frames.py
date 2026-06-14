# =============================================================================
# intelligence/key_frames.py — Key frame selection for Gemini video input
#
# What it does:
#   KeyFrameSelector picks the 10-12 most important frames from the capture
#   buffer to send to Gemini. It prioritizes: (1) frames where the score
#   changed, (2) scene cuts (camera angle switches), and (3) highest-motion
#   frames to fill remaining slots. Results are sorted chronologically and
#   tagged with their selection reason for the debug dashboard.
#
# Technologies:
#   - Pure Python — no external dependencies. Operates on frame metadata
#     dicts produced by FrameAnalyzer.
#
# Why it matters:
#   Gemini has limited video input capacity. Sending every frame would be
#   too large and too expensive. This module ensures the AI sees the most
#   relevant moments — score changes, camera cuts, and action — so it can
#   answer questions accurately with minimal input tokens.
# =============================================================================


class KeyFrameSelector:
    def __init__(self):
        self.last_selected = []

    def select(self, frames, max_frames=12):
        """Select up to max_frames key frames from the buffer by importance.

        Priority order:
          1. Score changed       — scoreboard pixel diff > threshold
          2. Pitcher throwing    — YOLO detected pitcher wind-up/release
          3. Batter swinging     — YOLO detected batter with arms raised
          4. Scene cuts          — histogram correlation drop (camera change)
          5. High motion score   — most pixels changed (action happening)
        """
        if not frames:
            return []

        selected_ids = set()
        selected = []

        def _add(f):
            if id(f) not in selected_ids:
                selected.append(f)
                selected_ids.add(id(f))

        # Priority 1: score changes — always include all
        for f in frames:
            if f.get("score_changed"):
                _add(f)

        # Priority 2: pitcher throwing
        for f in frames:
            if len(selected) >= max_frames:
                break
            if f.get("pitcher_throwing"):
                _add(f)

        # Priority 3: batter swinging
        for f in frames:
            if len(selected) >= max_frames:
                break
            if f.get("batter_swinging"):
                _add(f)

        # Priority 4: scene cuts (cap at 4)
        cut_count = 0
        for f in frames:
            if len(selected) >= max_frames or cut_count >= 4:
                break
            if f.get("is_scene_cut"):
                _add(f)
                cut_count += 1

        # Priority 5: highest motion score fills remaining slots
        remaining = max_frames - len(selected)
        if remaining > 0:
            candidates = [f for f in frames if id(f) not in selected_ids]
            candidates.sort(key=lambda f: f.get("motion_score", 0), reverse=True)
            for f in candidates[:remaining]:
                _add(f)

        # Sort chronologically so Gemini sees the clip in temporal order
        selected.sort(key=lambda f: f.get("timestamp", 0))
        selected = selected[:max_frames]

        # Tag selection reason for debugging
        for f in selected:
            if f.get("score_changed"):
                f["selection_reason"] = "score"
            elif f.get("pitcher_throwing"):
                f["selection_reason"] = "pitcher"
            elif f.get("batter_swinging"):
                f["selection_reason"] = "batter"
            elif f.get("is_scene_cut"):
                f["selection_reason"] = "cut"
            else:
                f["selection_reason"] = "motion"

        self.last_selected = selected
        return selected