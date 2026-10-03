"""Draws icon.ico: a dark tile with a teal globe split by an amber grey line
(the night side shaded), a glowing sun, and three Kp-style bars. Drawn at
1024 px and downsampled for crisp small sizes."""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 1024
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon.ico")

BG, EDGE = (20, 24, 29, 255), (108, 182, 255, 255)
TEAL, GREEN, AMBER, RED = (108, 182, 255), (87, 227, 154), (255, 191, 95), (255, 122, 107)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([40, 40, S - 40, S - 40], radius=190, fill=BG, outline=EDGE, width=30)

# globe
cx, cy, r = 430, 560, 300
globe = Image.new("RGBA", (S, S), (0, 0, 0, 0))
g = ImageDraw.Draw(globe)
g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(30, 58, 88, 255))
for k in (-2, -1, 0, 1, 2):                       # meridians
    w = abs(k) * r / 2.6
    g.ellipse([cx - r + w, cy - r, cx + r - w, cy + r], outline=TEAL + (200,), width=10)
for yy in (-0.55, 0, 0.55):                        # parallels
    y = cy + yy * r
    half = (r * r - (yy * r) ** 2) ** 0.5
    g.line([cx - half, y, cx + half, y], fill=TEAL + (200,), width=10)
night = Image.new("L", (S, S), 0)
ImageDraw.Draw(night).ellipse([cx - r * 0.35, cy - r * 1.25, cx + r * 2.2, cy + r * 1.25], fill=150)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
shade = Image.new("RGBA", (S, S), (0, 0, 0, 255))
shade.putalpha(ImageChops.multiply(night, mask))
globe = Image.alpha_composite(globe, shade)
line = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(line).arc([cx - r * 0.35, cy - r * 1.25, cx + r * 2.2, cy + r * 1.25], 120, 240,
                         fill=AMBER + (255,), width=26)
line.putalpha(ImageChops.multiply(line.getchannel("A"), mask))
glow = line.filter(ImageFilter.GaussianBlur(18))
globe = Image.alpha_composite(Image.alpha_composite(globe, glow), line)
ImageDraw.Draw(globe).ellipse([cx - r, cy - r, cx + r, cy + r], outline=TEAL + (255,), width=16)
img = Image.alpha_composite(img, globe)

# sun
sx, sy, sr = 745, 270, 95
sun = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sun).ellipse([sx - sr * 1.9, sy - sr * 1.9, sx + sr * 1.9, sy + sr * 1.9], fill=AMBER + (150,))
sun = sun.filter(ImageFilter.GaussianBlur(45))
img = Image.alpha_composite(img, sun)
d = ImageDraw.Draw(img)
d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=AMBER + (255,))
d.ellipse([sx - sr * 0.55, sy - sr * 0.6, sx - sr * 0.05, sy - sr * 0.2], fill=(255, 232, 190, 255))

# Kp bars
for i, (h, c) in enumerate(((150, GREEN), (230, AMBER), (310, RED))):
    x = 700 + i * 78
    d.rounded_rectangle([x, 880 - h, x + 58, 880], radius=12, fill=c + (255,))

img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
Image.open(OUT).convert("RGBA").resize((256, 256)).save(OUT.replace(".ico", "_preview.png"))
print("wrote", OUT)
