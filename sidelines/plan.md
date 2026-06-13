Update ui.py to match the Cluely visual style only — don't change any functionality or layout logic:

- Background: near-black with ~85% opacity / slight blur effect (use bg="#111111" with alpha 0.88)
- Shape: rounded corners (borderwidth=0, use overrideredirect, add corner rounding via Canvas or platform tricks)
- Font: SF Pro Display or system sans-serif, size 13-14, normal weight, white (#FFFFFF)
- No hard edges — the window should feel like a floating pill
- Subtle border: 1px rgba white at ~15% opacity
- Response text: slightly dimmer white (#CCCCCC), same font, line height feels airy
- Remove any gray/flat tkinter default styling — everything should feel dark, minimal, glassy

Do not change button positions, hotkey logic, or any behavior.