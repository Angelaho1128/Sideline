class KeyFrameSelector:
    def __init__(self):
        self.last_selected = []

    def select(self, frames, max_frames=12):
        """Select 10-12 key frames from the buffer based on importance."""
        if not frames:
            return []

        # Priority 1: score changes (always include)
        score_frames = [f for f in frames if f.get("score_changed")]

        # Priority 2: scene cuts (cap at 5)
        cut_frames = [
            f for f in frames
            if f.get("is_scene_cut") and f not in score_frames
        ]
        cut_frames = cut_frames[:5]

        selected = score_frames + cut_frames
        remaining = max_frames - len(selected)

        if remaining > 0:
            # Priority 3: highest motion score to fill remaining slots
            candidates = [f for f in frames if f not in selected]
            candidates.sort(
                key=lambda f: f.get("motion_score", 0), reverse=True
            )
            selected.extend(candidates[:remaining])

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
