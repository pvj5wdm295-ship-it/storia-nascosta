#!/usr/bin/env python3
"""Genera foto profilo (800x800) e banner (2560x1440) del canale "Scienza in Tasca"."""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
C1, C2 = (26, 11, 61), (106, 27, 154)          # viola dei video
GOLD, WHITE, CYAN = (255, 200, 40), (255, 255, 255), (170, 220, 255)
SS = 2                                          # supersampling


def gradient(w, h):
    g = Image.new("RGB", (64, 64))
    px = g.load()
    for y in range(64):
        for x in range(64):
            t = 0.7 * y / 63 + 0.3 * x / 63
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(C1, C2))
    return g.resize((w, h), Image.BICUBIC)


def glow(img, cx, cy, r, col, alpha=120, blur=None):
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse((cx - r, cy - r, cx + r, cy + r), fill=col + (alpha,))
    lay = lay.filter(ImageFilter.GaussianBlur(blur or r * 0.45))
    img.paste(lay, (0, 0), lay)


def stars(d, w, h, n, seed=1):
    import random
    rnd = random.Random(seed)
    for _ in range(n):
        x, y, r = rnd.uniform(0, w), rnd.uniform(0, h), rnd.choice([2, 3, 4, 5]) * SS
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rnd.randint(70, 200)))


def logo(img, cx, cy, s):
    """Tasca (taschino cucito) da cui spunta un atomo luminoso. s = scala in px."""
    d = ImageDraw.Draw(img, "RGBA")
    # atomo che esce dalla tasca
    ay = cy - 0.30 * s
    glow(img, cx, ay, 0.55 * s, CYAN, 140)
    d = ImageDraw.Draw(img, "RGBA")
    for ang in (0, 60, 120):
        lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(lay).ellipse((cx - 0.62 * s, ay - 0.22 * s, cx + 0.62 * s, ay + 0.22 * s),
                                    outline=CYAN + (255,), width=int(0.045 * s))
        lay = lay.rotate(ang, center=(cx, ay), resample=Image.BICUBIC)
        img.paste(lay, (0, 0), lay)
    d = ImageDraw.Draw(img, "RGBA")
    r = 0.15 * s
    d.ellipse((cx - r, ay - r, cx + r, ay + r), fill=GOLD + (255,), outline=WHITE, width=int(0.02 * s))
    for a in (20, 140, 260):
        t = math.radians(a)
        ex, ey = cx + 0.55 * s * math.cos(t), ay + 0.19 * s * math.sin(t)
        e = 0.05 * s
        d.ellipse((ex - e, ey - e, ex + e, ey + e), fill=(120, 255, 200, 255))
    # tasca: forma a scudo
    top, bot, hw = cy + 0.02 * s, cy + 0.78 * s, 0.62 * s
    poly = [(cx - hw, top), (cx + hw, top), (cx + hw, bot - 0.22 * s), (cx, bot), (cx - hw, bot - 0.22 * s)]
    d.polygon(poly, fill=(240, 240, 250, 255))
    # bordo superiore (risvolto) + cuciture tratteggiate
    d.rounded_rectangle((cx - hw - 0.04 * s, top - 0.05 * s, cx + hw + 0.04 * s, top + 0.12 * s),
                        radius=int(0.05 * s), fill=GOLD + (255,))
    inset = 0.08 * s
    pts = [(cx - hw + inset, top + 0.2 * s), (cx - hw + inset, bot - 0.25 * s), (cx, bot - inset * 1.1),
           (cx + hw - inset, bot - 0.25 * s), (cx + hw - inset, top + 0.2 * s)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        n = int(L / (0.07 * s))
        for k in range(0, n, 2):
            a0, a1 = k / n, min(1, (k + 1) / n)
            d.line([(x0 + (x1 - x0) * a0, y0 + (y1 - y0) * a0), (x0 + (x1 - x0) * a1, y0 + (y1 - y0) * a1)],
                   fill=(150, 120, 200, 255), width=max(2, int(0.022 * s)))


def text_center(d, txt, cx, cy, size, fill=WHITE, stroke=0):
    f = ImageFont.truetype(FONT, size)
    w = d.textlength(txt, font=f)
    d.text((cx - w / 2, cy - size * 0.6), txt, font=f, fill=fill,
           stroke_width=stroke, stroke_fill=(0, 0, 0, 160))


def profile():
    N = 800 * SS
    img = gradient(N, N)
    d = ImageDraw.Draw(img, "RGBA")
    stars(d, N, N, 40)
    glow(img, N / 2, N / 2, N * 0.42, (180, 120, 255), 90)
    logo(img, N / 2, N * 0.45, N * 0.42)
    img.resize((800, 800), Image.LANCZOS).save(OUT / "foto_profilo_800.png")


def banner():
    Wb, Hb = 2560 * SS, 1440 * SS
    img = gradient(Wb, Hb)
    d = ImageDraw.Draw(img, "RGBA")
    stars(d, Wb, Hb, 260, seed=7)
    # area sicura YouTube: 1546x423 al centro
    cx, cy = Wb / 2, Hb / 2
    glow(img, cx - 540 * SS, cy, 230 * SS, (180, 120, 255), 90)
    logo(img, cx - 540 * SS, cy - 5 * SS, 165 * SS)
    d = ImageDraw.Draw(img, "RGBA")
    text_center(d, "SCIENZA IN TASCA", cx + 150 * SS, cy - 40 * SS, 96 * SS, stroke=4 * SS)
    text_center(d, "La scienza in meno di un minuto", cx + 150 * SS, cy + 75 * SS, 46 * SS, fill=GOLD + (255,))
    img.resize((2560, 1440), Image.LANCZOS).save(OUT / "banner_2560x1440.png")


if __name__ == "__main__":
    profile()
    banner()
    print("ok")
