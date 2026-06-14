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
        """Select 10-12 key frames from the buffer based on importance."""
        if not frames:
            return []

        # Priority 1: score changes (always include)
        score_frames = [f for f in frames if f.get("score_changed")]
        selected_ids = {id(f) for f in score_frames}

        # Priority 2: scene cuts (cap at 5)
        cut_frames = [
            f for f in frames
            if f.get("is_scene_cut") and id(f) not in selected_ids
        ]
        cut_frames = cut_frames[:5]

        selected = score_frames + cut_frames
        selected_ids.update(id(f) for f in cut_frames)
        remaining = max_frames - len(selected)

        if remaining > 0:
            # Priority 3: fill remaining slots with a mix of high-motion
            # and recent frames. Recent frames matter most for "what just
            # happened?" questions, but high-motion frames capture the action.
            candidates = [f for f in frames if id(f) not in selected_ids]

            # Reserve half the remaining slots for the most recent frames
            recent_slots = remaining // 2
            motion_slots = remaining - recent_slots

            # Highest motion frames
            by_motion = sorted(
                candidates,
                key=lambda f: f.get("motion_score", 0), reverse=True,
            )
            motion_picks = by_motion[:motion_slots]
            selected.extend(motion_picks)
            selected_ids.update(id(f) for f in motion_picks)

            # Most recent frames (by timestamp, descending)
            remaining_cands = [f for f in candidates if id(f) not in selected_ids]
            by_recency = sorted(
                remaining_cands,
                key=lambda f: f.get("timestamp", 0), reverse=True,
            )
            selected.extend(by_recency[:recent_slots])

        # Sort chronologically
        selected.sort(key=lambda f: f.get("timestamp", 0))
        selected = selected[:max_frames]

        # Tag selection reason for dashboard display
        for f in selected:
            if f.get("score_changed"):
                f["selection_reason"] = "score"
            elif f.get("is_scene_cut"):
                f["selection_reason"] = "cut"
            else:
                f["selection_reason"] = "motion"

        self.last_selected = selected
        return selected
