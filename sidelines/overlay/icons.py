"""Vector-ish UI icons rendered with PIL into RGBA images.

Everything is drawn at 4x and downsampled with LANCZOS so the strokes stay
crisp on Retina displays. All icons are white-on-transparent unless a color
is supplied, matching the dark-glass overlay aesthetic.
"""

import os

from PIL import Image, ImageDraw

SS = 4  # supersampling factor

_ASSETS = os.path.join(os.path.dirname(__file__), "assets")
_BRAND_LOGO = os.path.join(_ASSETS, "brand_logo.png")


def _canvas(size):
    """A transparent square RGBA canvas at supersampled resolution."""
    return Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))


def _finish(img, size):
    return img.resize((size, size), Image.LANCZOS)


# Classic lightning bolt, normalized to a unit box (x right, y down).
_BOLT = [
    (0.58, 0.03),
    (0.20, 0.55),
    (0.45, 0.55),
    (0.38, 0.97),
    (0.82, 0.40),
    (0.55, 0.40),
    (0.62, 0.03),
]


def bolt(size, color=(255, 255, 255, 255), pad=0.16):
    """A filled lightning bolt."""
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    span = 1.0 - 2 * pad
    pts = [(pad * s + x * span * s, pad * s + y * span * s) for x, y in _BOLT]
    d.polygon(pts, fill=color)
    return _finish(img, size)


def brand_logo(height=22, color=(255, 255, 255, 255)):
    """Sidelines brand mark from assets, recolored for the dark overlay."""
    src = Image.open(_BRAND_LOGO).convert("RGBA")
    gray = src.convert("L")
    alpha = gray.point(lambda p: 255 - p if p < 240 else 0)
    img = Image.new("RGBA", src.size, color)
    img.putalpha(alpha)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    width = max(1, round(img.width * height / img.height))
    return img.resize((width, height), Image.LANCZOS)


def sparkle(size, color=(255, 255, 255, 255)):
    """Four-pointed sparkle beside assistant messages."""
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    cx, cy = s * 0.5, s * 0.5
    arm = s * 0.38
    lw = max(SS, int(s * 0.11))
    d.line([cx, cy - arm, cx, cy + arm], fill=color, width=lw)
    d.line([cx - arm, cy, cx + arm, cy], fill=color, width=lw)
    return _finish(img, size)


def logo(size=28, radius=0.30):
    """Lightning bolt inside a glassy, vertically-graduated rounded square."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Vertical gradient: lighter at the top, darker at the bottom.
    grad = Image.new("RGBA", (1, s))
    top = (96, 98, 104)
    bot = (40, 41, 46)
    for y in range(s):
        t = y / max(1, s - 1)
        grad.putpixel((0, y), (
            int(top[0] + (bot[0] - top[0]) * t),
            int(top[1] + (bot[1] - top[1]) * t),
            int(top[2] + (bot[2] - top[2]) * t),
            255,
        ))
    grad = grad.resize((s, s))

    # Rounded-rect mask to clip the gradient.
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=int(radius * s), fill=255
    )
    img.paste(grad, (0, 0), mask)

    # Hairline top highlight + outer border for the glassy edge.
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=int(radius * s),
        outline=(255, 255, 255, 60), width=max(1, SS),
    )

    # White bolt centered inside.
    b = bolt(size, color=(255, 255, 255, 255), pad=0.26)
    img.alpha_composite(b.resize((s, s), Image.LANCZOS))
    return _finish(img, size)


def mic(size, color=(255, 255, 255, 255), width=0.07):
    """Outline microphone glyph."""
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    lw = max(SS, int(width * s))

    cx = s * 0.5
    cap_w = s * 0.30
    cap_top = s * 0.12
    cap_bot = s * 0.52
    # Capsule body (rounded rect outline).
    d.rounded_rectangle(
        [cx - cap_w / 2, cap_top, cx + cap_w / 2, cap_bot],
        radius=cap_w / 2, outline=color, width=lw,
    )
    # U-shaped cradle arc beneath the capsule.
    arc_w = s * 0.50
    arc_top = s * 0.30
    arc_bot = s * 0.68
    d.arc(
        [cx - arc_w / 2, arc_top, cx + arc_w / 2, arc_bot],
        start=20, end=160, fill=color, width=lw,
    )
    # Stem + base.
    d.line([cx, arc_bot - lw * 0.4, cx, s * 0.86], fill=color, width=lw)
    d.line([cx - s * 0.16, s * 0.86, cx + s * 0.16, s * 0.86], fill=color, width=lw)
    return _finish(img, size)


def speaker(size, color=(255, 255, 255, 255), width=0.07):
    """A speaker/volume icon for TTS playback."""
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    lw = max(SS, int(width * s))
    # Speaker body (rectangle)
    d.rectangle([s * 0.18, s * 0.35, s * 0.35, s * 0.65], fill=color)
    # Speaker cone (triangle)
    d.polygon([(s * 0.35, s * 0.35), (s * 0.55, s * 0.18),
               (s * 0.55, s * 0.82), (s * 0.35, s * 0.65)], fill=color)
    # Sound waves (arcs)
    d.arc([s * 0.58, s * 0.30, s * 0.75, s * 0.70], -45, 45, fill=color, width=lw)
    d.arc([s * 0.65, s * 0.18, s * 0.88, s * 0.82], -45, 45, fill=color, width=lw)
    return _finish(img, size)


def chevron(size, direction="left", color=(255, 255, 255, 255), width=0.12):
    """A single chevron ‹ or ›."""
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    lw = max(SS, int(width * s))
    top = s * 0.22
    mid = s * 0.5
    bot = s * 0.78
    if direction == "left":
        near, far = s * 0.62, s * 0.38
    else:
        near, far = s * 0.38, s * 0.62
    d.line([near, top, far, mid], fill=color, width=lw, joint="curve")
    d.line([far, mid, near, bot], fill=color, width=lw, joint="curve")
    return _finish(img, size)


# Filled "send" paper-plane arrow, normalized to a unit box (x right, y down):
# a right-pointing triangle with a V-notch cut into its trailing (left) edge.
_SEND = [
    (0.93, 0.50),   # tip (right)
    (0.11, 0.15),   # back-top
    (0.40, 0.50),   # notch (concave, toward tip)
    (0.11, 0.85),   # back-bottom
]


def send(size, color=(255, 255, 255, 255), pad=0.10):
    """A filled right-pointing send arrow (paper-plane glyph)."""
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    s = size * SS
    span = 1.0 - 2 * pad
    pts = [(pad * s + x * span * s, pad * s + y * span * s) for x, y in _SEND]
    d.polygon(pts, fill=color)
    return _finish(img, size)
