# =============================================================================
# utils/config.py — Configuration persistence (config.json)
#
# What it does:
#   Manages a JSON config file (config.json in the project root) that stores
#   app settings: capture FPS, buffer duration, scoreboard ROI coordinates,
#   and broadcast presets. load_config() reads or creates the file with
#   sensible defaults; save_config() writes it back. Used by main.py on
#   startup and by RegionSelector when the user picks a scoreboard region.
#
# Technologies:
#   - Python json module for serialization
#   - os.path for cross-platform file path resolution
#
# Why it matters:
#   Without persistent config, users would have to re-select the scoreboard
#   region every time they launch the app. This module keeps settings across
#   sessions. The defaults (3 FPS, 30s buffer, ESPN preset) are tuned for
#   baseball broadcasts and provide a working out-of-the-box experience.
# =============================================================================

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

DEFAULT_CONFIG = {
    "fps": 3,
    "buffer_seconds": 30,
    "scoreboard_roi": None,
    "presets": {
        "espn_baseball": {"top": 40, "left": 50, "width": 350, "height": 85}
    }
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
