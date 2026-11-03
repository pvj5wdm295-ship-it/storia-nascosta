"""
animations.py - Scene animate (fotogramma per fotogramma) per make_video.py.

Ogni scena animata è una classe con:
    __init__(self, rnd)            pre-calcoli (traiettorie, sprite…)
    draw(self, f, t, T)            disegna sul fotogramma f (Frame) al tempo t di una scena lunga T
Le classi si registrano in ANIMS con il nome usato nel JSON ("anim": "nome").

Disegno con aggdraw (bordi antialias) su immagini RGB 1080x1920; aloni e testi sono sprite
pre-calcolati incollati con maschera alfa.
"""
import math
import random
from functools import lru_cache

import aggdraw
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CONTENT_Y = 720          # centro verticale della zona animata (testo in alto, sottotitoli sotto)


# ============================================================================ utilità

def ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def ease_out_back(u, k=1.70158):
    u = min(max(u, 0.0), 1.0) - 1
    return 1 + (k + 1) * u ** 3 + k * u ** 2


def lerp(a, b, u):
    return a + (b - a) * u


def mixc(c1, c2, u):
    return tuple(int(lerp(a, b, u)) for a, b in zip(c1, c2))


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@lru_cache(maxsize=64)
def glow_sprite(radius, color, alpha=150):
    """Alone sfumato (RGBA) di raggio ~radius."""
    blur = radius * 0.42
    s = int(2 * radius + 7 * blur)
    im = Image.new("RGBA", (s, s), color + (0,))
    ImageDraw.Draw(im).ellipse((s / 2 - radius, s / 2 - radius, s / 2 + radius, s / 2 + radius),
                               fill=color + (alpha,))
    return im.filter(ImageFilter.GaussianBlur(blur))


@lru_cache(maxsize=256)
def font(size):
    return ImageFont.truetype(FONT_BOLD, size)


@lru_cache(maxsize=128)
def text_sprite(text, size, fill=(255, 255, 255), stroke=6, max_w=960):
    """Testo centrato e a capo, con contorno e ombra, come sprite RGBA."""
    f = font(size)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if tmp.textlength(t, font=f) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    lh = int(size * 1.15)
    wmax = int(max(tmp.textlength(l, font=f) for l in lines)) + 2 * stroke + 12
    im = Image.new("RGBA", (wmax, lh * len(lines) + 2 * stroke + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k, ln in enumerate(lines):
        x = (wmax - d.textlength(ln, font=f)) / 2
        y = stroke + k * lh
        d.text((x + 4, y + 6), ln, font=f, fill=(0, 0, 0, 150))
        d.text((x, y), ln, font=f, fill=fill + (255,), stroke_width=stroke, stroke_fill=(0, 0, 0, 220))
    return im


class Frame:
    """Fotogramma RGB + pennello aggdraw. Alterna i due livelli con flush()."""

    def __init__(self, base):
        self.img = base.copy()
        self.d = aggdraw.Draw(self.img)

    def flush(self):
        self.d.flush()

    def paste(self, sprite, cx, cy, scale=1.0, opacity=1.0):
        self.d.flush()
        sp = sprite
        if abs(scale - 1) > 1e-3:
            w, h = max(1, int(sp.width * scale)), max(1, int(sp.height * scale))
            sp = sp.resize((w, h), Image.BILINEAR)
        if opacity < 0.999:
            a = sp.getchannel("A").point(lambda v: int(v * max(0.0, opacity)))
            sp = sp.copy()
            sp.putalpha(a)
        self.img.paste(sp, (int(cx - sp.width / 2), int(cy - sp.height / 2)), sp)
        self.d = aggdraw.Draw(self.img)

    # primitive con colore RGB + opacità 0..1
    def circle(self, x, y, r, fill=None, a=1.0, outline=None, width=0, oa=1.0):
        pen = aggdraw.Pen(outline, width, int(255 * oa)) if outline else None
        br = aggdraw.Brush(fill, int(255 * a)) if fill else None
        args = [p for p in (pen, br) if p is not None]
        self.d.ellipse((x - r, y - r, x + r, y + r), *args)

    def ellipse(self, box, fill=None, a=1.0, outline=None, width=0, oa=1.0):
        pen = aggdraw.Pen(outline, width, int(255 * oa)) if outline else None
        br = aggdraw.Brush(fill, int(255 * a)) if fill else None
        self.d.ellipse(box, *[p for p in (pen, br) if p is not None])

    def line(self, pts, color, width, a=1.0):
        flat = [v for p in pts for v in p]
        self.d.line(flat, aggdraw.Pen(color, width, int(255 * a)))

    def polygon(self, pts, fill, a=1.0):
        self.d.polygon([v for p in pts for v in p], aggdraw.Brush(fill, int(255 * a)))

    def arc(self, box, start, end, color, width, a=1.0):
        self.d.arc(box, start, end, aggdraw.Pen(color, width, int(255 * a)))


# ============================================================================ elementi comuni

class Starfield:
    def __init__(self, rnd, n=130):
        self.stars = [(rnd.uniform(0, W), rnd.uniform(0, H), rnd.choice([1.2, 1.6, 2.2, 3.0]),
                       rnd.choice([1, 2, 3]), rnd.uniform(0, 6.28), rnd.uniform(1.5, 4)) for _ in range(n)]

    def draw(self, f, t):
        for x, y, r, layer, ph, sp in self.stars:
            yy = (y + t * 6 * layer) % H
            tw = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(ph + t * sp))
            f.circle(x, yy, r * (0.8 + 0.2 * layer), fill=(255, 255, 255), a=tw * (0.35 + 0.2 * layer))


def disk_color(u):
    """u 0 (interno, bianco-giallo) -> 1 (esterno, rosso-arancio)."""
    stops = [(255, 250, 225), (255, 205, 90), (255, 130, 30), (190, 50, 20)]
    u = min(max(u, 0), 1) * (len(stops) - 1)
    k = min(int(u), len(stops) - 2)
    return mixc(stops[k], stops[k + 1], u - k)


def black_hole(f, x, y, r, t, tilt=0.26, spin=1.0, particles=None, glow=True, alpha=1.0):
    """Buco nero con disco di accrescimento rotante, anello di fotoni e lente gravitazionale."""
    if glow:
        f.paste(glow_sprite(int(r * 2.4), (255, 140, 40), int(110 * alpha)), x, y)
    rings = [r * k for k in (1.55, 1.8, 2.05, 2.3, 2.6, 2.9)]
    seg = 15

    def disk_half(front):
        for i, R in enumerate(rings):
            u = i / (len(rings) - 1)
            col = disk_color(u)
            wdt = max(2, r * 0.16 * (1 - 0.4 * u))
            for a0 in range(0 if front else 180, 180 if front else 360, seg):
                am = math.radians(a0 + seg / 2)
                # effetto Doppler (lato in avvicinamento più brillante) + "grumi" che ruotano
                dop = 0.55 + 0.45 * math.cos(am + 0.4)
                clump = 0.75 + 0.25 * math.sin(3 * am - spin * t * (3.2 - 1.6 * u) + i)
                f.arc((x - R, y - R * tilt, x + R, y + R * tilt), a0, a0 + seg + 1, col, wdt,
                      a=alpha * min(1, dop * clump * (1.05 - 0.45 * u)))

    def dots(front):
        if not particles:
            return
        for R, a0, sz in particles:
            ang = a0 + spin * t * 2.6 * (r * 1.6 / R) ** 1.5
            px, py = x + R * math.cos(ang), y + R * tilt * math.sin(ang)
            if (math.sin(ang) > 0) == front:
                f.circle(px, py, sz, fill=(255, 240, 200), a=alpha * 0.9)

    disk_half(False)
    dots(False)
    # immagine "lensata" della parte posteriore del disco: arco sopra e sotto l'ombra
    for k, (rr, a) in enumerate(((1.32, 0.95), (1.48, 0.6), (1.62, 0.3))):
        f.arc((x - r * rr, y - r * rr, x + r * rr, y + r * rr), 180, 360, disk_color(0.2 + 0.25 * k),
              max(2, r * 0.13), a=alpha * a)
        f.arc((x - r * rr, y - r * rr, x + r * rr, y + r * rr), 0, 180, disk_color(0.3 + 0.25 * k),
              max(2, r * 0.06), a=alpha * a * 0.45)
    f.circle(x, y, r * 1.08, outline=(255, 245, 210), width=max(2, r * 0.05), oa=alpha * 0.95)
    f.circle(x, y, r, fill=(0, 0, 0), a=alpha)
    disk_half(True)
    dots(True)


@lru_cache(maxsize=4)
def astronaut_sprite(h=260):
    """Astronauta stilizzato (RGBA), alto h px."""
    s = 4
    w = int(h * 0.62)
    im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    S = lambda *v: [p * s for p in v]
    white, grey, visor = (245, 245, 250, 255), (180, 185, 200, 255), (255, 170, 60, 255)
    cx = w / 2
    d.rounded_rectangle(S(cx - 0.36 * w, 0.30 * h, cx + 0.36 * w, 0.70 * h), radius=0.12 * w * s, fill=white)
    d.rounded_rectangle(S(cx - 0.50 * w, 0.32 * h, cx - 0.30 * w, 0.62 * h), radius=0.08 * w * s, fill=grey)
    d.rounded_rectangle(S(cx + 0.30 * w, 0.32 * h, cx + 0.50 * w, 0.62 * h), radius=0.08 * w * s, fill=grey)
    d.rounded_rectangle(S(cx - 0.30 * w, 0.66 * h, cx - 0.06 * w, 1.0 * h), radius=0.08 * w * s, fill=white)
    d.rounded_rectangle(S(cx + 0.06 * w, 0.66 * h, cx + 0.30 * w, 1.0 * h), radius=0.08 * w * s, fill=white)
    d.ellipse(S(cx - 0.34 * w, 0.0, cx + 0.34 * w, 0.36 * h), fill=white)
    d.ellipse(S(cx - 0.24 * w, 0.07 * h, cx + 0.24 * w, 0.28 * h), fill=visor)
    d.ellipse(S(cx - 0.14 * w, 0.10 * h, cx - 0.02 * w, 0.16 * h), fill=(255, 235, 200, 255))
    d.rectangle(S(cx - 0.14 * w, 0.42 * h, cx + 0.14 * w, 0.52 * h), fill=(90, 160, 255, 255))
    return im.resize((w, h), Image.LANCZOS)


def stretched(sprite, sx, sy, angle):
    w, h = max(1, int(sprite.width * sx)), max(1, int(sprite.height * sy))
    return sprite.resize((w, h), Image.BILINEAR).rotate(angle, expand=True, resample=Image.BILINEAR)


def arrow(f, x0, y0, x1, y1, color, width, a=1.0, head=None):
    head = head or width * 2.6
    ang = math.atan2(y1 - y0, x1 - x0)
    bx, by = x1 - head * math.cos(ang), y1 - head * math.sin(ang)
    f.line([(x0, y0), (bx, by)], color, width, a)
    f.polygon([(x1, y1), (bx + head * 0.6 * math.sin(ang), by - head * 0.6 * math.cos(ang)),
               (bx - head * 0.6 * math.sin(ang), by + head * 0.6 * math.cos(ang))], color, a)


# ============================================================================ scene

class Spaghetti:
    """Gancio: un astronauta cade a spirale nel buco nero e si allunga come uno spaghetto."""

    def __init__(self, rnd):
        self.parts = [(rnd.uniform(1.6, 2.9) * 120, rnd.uniform(0, 6.28), rnd.uniform(2, 4)) for _ in range(26)]

    def draw(self, f, t, T):
        x, y, r = 540, CONTENT_Y + 60, 120
        black_hole(f, x, y, r, t, particles=self.parts)
        u = ease(min(t / (T * 0.92), 1))
        R = lerp(520, r * 0.9, u ** 1.3)
        ang = math.radians(-60 + 300 * u)
        px, py = x + R * math.cos(ang), y + R * 0.55 * math.sin(ang)
        stretch = 1 + 3.2 * u ** 2.2
        thin = 1 / (1 + 1.2 * u ** 2)
        size = lerp(1.0, 0.35, u)
        rot = -math.degrees(math.atan2(y - py, x - px)) - 90
        sp = stretched(astronaut_sprite(), thin * size, stretch * size, rot + 180 * u)
        f.paste(sp, px, py, opacity=1 - ease((u - 0.85) / 0.15))


class Accretion:
    """Buco nero grande, disco rotante e particelle che spiraleggiano dentro."""

    def __init__(self, rnd):
        self.parts = [(rnd.uniform(1.6, 2.9) * 170, rnd.uniform(0, 6.28), rnd.uniform(2, 5)) for _ in range(40)]
        self.fall = [(rnd.uniform(0, 1), rnd.uniform(0, 6.28), rnd.uniform(2.5, 4.5)) for _ in range(28)]

    def draw(self, f, t, T):
        x, y, r = 540, CONTENT_Y + 40, 170
        black_hole(f, x, y, r, t, particles=self.parts)
        for ph, a0, sz in self.fall:      # materia che precipita a spirale
            u = (t / 2.2 + ph) % 1
            R = lerp(560, r * 1.05, u ** 0.8)
            ang = a0 + 7 * u ** 2
            f.circle(x + R * math.cos(ang), y + R * 0.5 * math.sin(ang), sz * (1 - 0.5 * u),
                     fill=(170, 220, 255), a=0.85 * (1 - u ** 4))


class LightBend:
    """Raggi di luce che passano vicino al buco nero: alcuni si piegano, altri vengono catturati."""

    def __init__(self, rnd):
        self.x, self.y, self.r = 540, CONTENT_Y + 40, 95
        self.rays = []
        for k, b in enumerate([-470, -360, -270, -200, -150, -75, 0, 75, 150, 200, 270, 360, 470]):
            pts, cap = self._trace(b)
            self.rays.append((pts, cap, (k * 0.37) % 1.6))

    def _trace(self, b):
        x, y, vx, vy = -60.0, self.y + b, 1.0, 0.0
        GM, pts = 52.0, []
        for _ in range(2400):
            dx, dy = x - self.x, y - self.y
            d = math.hypot(dx, dy)
            if d < self.r:
                return pts, True
            acc = GM / (d * d)
            vx -= acc * dx / d
            vy -= acc * dy / d
            n = math.hypot(vx, vy)
            vx, vy = vx / n, vy / n                     # la luce va sempre alla stessa velocità
            x += vx * 1.0
            y += vy * 1.0
            pts.append((x, y))
            if x > W + 60 or y < -60 or y > H + 60:
                break
        return pts, False

    def draw(self, f, t, T):
        speed, trail = 900, 360                          # px/s, lunghezza scia in punti
        for pts, cap, delay in self.rays:
            n = int(((t + delay) % 2.6) * speed)
            if n <= 1:
                continue
            seg = pts[max(0, n - trail):min(n, len(pts))]
            if len(seg) < 2:
                continue
            col = (255, 230, 120) if cap else (170, 225, 255)
            step = max(1, len(seg) // 8)
            for k in range(0, len(seg) - step, step):
                f.line(seg[k:k + step + 1], col, 14, a=0.10 + 0.25 * k / len(seg))
                f.line(seg[k:k + step + 1], col, 6, a=0.20 + 0.80 * k / len(seg))
            if n < len(pts):
                hx, hy = seg[-1]
                f.circle(hx, hy, 16, fill=col, a=0.35)
                f.circle(hx, hy, 9, fill=(255, 255, 255))
        x, y, r = self.x, self.y, self.r
        f.paste(glow_sprite(int(r * 1.8), (120, 90, 255), 90), x, y)
        f.circle(x, y, r, fill=(0, 0, 0))
        pulse = 0.5 + 0.5 * math.sin(t * 5)
        for k in range(24):                             # orizzonte degli eventi tratteggiato
            a0 = k * 15 + t * 20
            f.arc((x - r - 14, y - r - 14, x + r + 14, y + r + 14), a0, a0 + 8, (255, 90, 90), 6,
                  a=0.55 + 0.45 * pulse)


class Stretch:
    """Testa contro piedi: la differenza di gravità allunga il corpo."""

    def __init__(self, rnd):
        self.parts = [(rnd.uniform(1.6, 2.9) * 80, rnd.uniform(0, 6.28), rnd.uniform(1.5, 3)) for _ in range(18)]

    def draw(self, f, t, T):
        bx, by, br = 540, CONTENT_Y + 360, 80
        black_hole(f, bx, by, br, t, particles=self.parts)
        u = ease(min(t / (T * 0.8), 1))
        sy, sx = 1 + 1.1 * u, 1 - 0.38 * u
        sp = stretched(astronaut_sprite(300), sx, sy * 0.9, 0)
        cy = by - br * 1.9 - sp.height / 2
        f.paste(sp, 540, cy)
        top, bottom = cy - sp.height / 2, cy + sp.height / 2
        wob = 6 * math.sin(t * 6)
        arrow(f, 760, top + 40, 760, top + 40 + 50 + wob, (170, 225, 255), 12)
        arrow(f, 760, bottom - 120, 760, bottom - 120 + 150 + 2 * wob, (255, 90, 90), 22)
        f.paste(text_sprite("debole", 40, (170, 225, 255), 4), 880, top + 60)
        f.paste(text_sprite("FORTE", 52, (255, 110, 110), 5), 890, bottom - 40)


class Clocks:
    """Il tempo rallenta: orologio lontano veloce, orologio vicino al buco nero lentissimo."""

    def __init__(self, rnd):
        self.parts = [(rnd.uniform(1.6, 2.9) * 70, rnd.uniform(0, 6.28), rnd.uniform(1.5, 3)) for _ in range(14)]

    def clock(self, f, x, y, R, ang, tint, label, lcol):
        f.circle(x, y, R, fill=(250, 250, 255), outline=tint, width=14)
        for k in range(12):
            a = math.radians(k * 30)
            f.line([(x + 0.78 * R * math.cos(a), y + 0.78 * R * math.sin(a)),
                    (x + 0.9 * R * math.cos(a), y + 0.9 * R * math.sin(a))], (40, 40, 60), 6)
        f.line([(x, y), (x + 0.5 * R * math.cos(ang / 12 - 1.57), y + 0.5 * R * math.sin(ang / 12 - 1.57))],
               (40, 40, 60), 12)
        f.line([(x, y), (x + 0.8 * R * math.cos(ang - 1.57), y + 0.8 * R * math.sin(ang - 1.57))], tint, 8)
        f.circle(x, y, 12, fill=tint)
        f.paste(text_sprite(label, 44, lcol, 4), x, y - R - 50)

    def draw(self, f, t, T):
        self.clock(f, 290, CONTENT_Y - 40, 170, t * 2 * math.pi / 1.5, (60, 140, 255), "LONTANO", (170, 225, 255))
        slow = t * 2 * math.pi / 14
        self.clock(f, 790, CONTENT_Y - 40, 170, slow, (255, 80, 80), "VICINO", (255, 140, 140))
        black_hole(f, 790, CONTENT_Y + 300, 70, t, particles=self.parts)
        f.paste(text_sprite("1 s", 54, (255, 255, 255), 5), 290, CONTENT_Y + 200)
        f.paste(text_sprite("...", 54, (255, 255, 255), 5), 790, CONTENT_Y + 175)


class Galaxy:
    """Via Lattea che ruota, con Sagittarius A* al centro."""

    def __init__(self, rnd):
        self.pts = []
        for arm in range(4):
            for _ in range(190):
                s = rnd.uniform(0.05, 1)
                th = arm * math.pi / 2 + 3.2 * s + rnd.gauss(0, 0.22)
                self.pts.append((s * 430 + rnd.gauss(0, 14), th, rnd.uniform(1.4, 3.6), s))

    def draw(self, f, t, T):
        x, y = 540, CONTENT_Y + 20
        f.paste(glow_sprite(260, (200, 170, 255), 110), x, y)
        for R, th, sz, s in self.pts:
            a = th + t * 0.35 * (1.2 - s)
            col = mixc((255, 240, 200), (150, 190, 255), s)
            f.circle(x + R * math.cos(a), y + R * 0.62 * math.sin(a), sz, fill=col, a=0.9 - 0.4 * s)
        f.paste(glow_sprite(80, (255, 230, 170), 200), x, y)
        p = (t * 1.2) % 1
        f.circle(x, y, 18 + 90 * p, outline=(255, 90, 90), width=6, oa=1 - p)
        f.circle(x, y, 14, fill=(0, 0, 0), outline=(255, 120, 90), width=4)
        pop = ease_out_back(min(max((t - 0.5) / 0.4, 0), 1))
        if pop > 0:
            f.paste(text_sprite("Sagittarius A*", 46, (255, 200, 120), 5), x, y + 130, scale=pop)


class FirstPhoto:
    """2019: la prima "foto" di un buco nero (M87*) che si compone dai dati dei radiotelescopi."""

    def __init__(self, rnd):
        self.parts = []
        for _ in range(420):
            a = rnd.uniform(0, 6.28)
            rr = rnd.gauss(170, 22)
            bright = 0.55 + 0.45 * math.sin(a + 0.6)          # più luminoso in basso, come nella foto vera
            self.parts.append((rnd.uniform(-80, W + 80), rnd.uniform(200, 1300), a, rr, bright, rnd.uniform(0, 0.35)))
        im = Image.new("RGBA", (700, 700), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for k in range(36):
            a0 = k * 10
            b = 0.55 + 0.45 * math.sin(math.radians(a0 + 5) + 0.6)
            d.arc((175, 175, 525, 525), a0, a0 + 11, fill=disk_color(0.95 - 0.7 * b) + (int(255 * b),), width=70)
        self.ring = im.filter(ImageFilter.GaussianBlur(26))

    def draw(self, f, t, T):
        x, y = 540, CONTENT_Y + 30
        for k, dx in enumerate((-330, 0, 330)):                # radiotelescopi + onde
            bx, by = x + dx, CONTENT_Y + 400
            f.polygon([(bx - 22, by + 55), (bx + 22, by + 55), (bx + 6, by - 5), (bx - 6, by - 5)], (200, 205, 225))
            dish = [(bx + 70 * math.cos(math.radians(a)), by - 20 + 38 * math.sin(math.radians(a)))
                    for a in range(0, 181, 12)]
            f.polygon([(bx - 75, by - 30), (bx + 75, by - 30)] + dish, (235, 238, 250))
            f.line([(bx, by - 25), (bx, by - 75)], (235, 238, 250), 5)
            f.circle(bx, by - 78, 8, fill=(255, 200, 80))
            w = ((t * 1.3 + k * 0.3) % 1)
            f.arc((bx - 40 - 70 * w, by - 150 - 70 * w, bx + 40 + 70 * w, by - 70 + 70 * w), 230, 310,
                  (140, 220, 255), 5, a=1 - w)
        u = ease(min(t / (T * 0.55), 1))
        for sx, sy, a, rr, b, dl in self.parts:
            v = ease((u - dl) / (1 - dl)) if u > dl else 0
            px, py = lerp(sx, x + rr * math.cos(a), v), lerp(sy, y + rr * math.sin(a), v)
            f.circle(px, py, 3.5, fill=disk_color(0.95 - 0.7 * b), a=0.35 + 0.6 * b)
        g = ease((t - T * 0.45) / (T * 0.3))
        if g > 0:
            f.paste(self.ring, x, y, opacity=g)
            f.paste(text_sprite("M87*", 46, (255, 210, 150), 5), x + 300, y - 230, opacity=g)


class Hawking:
    """Il buco nero evapora: coppie di particelle sull'orizzonte, una cade e una scappa."""

    def __init__(self, rnd):
        self.pairs = [(rnd.uniform(0, 6.28), rnd.uniform(0, 1)) for _ in range(34)]
        self.parts = [(rnd.uniform(1.6, 2.9) * 140, rnd.uniform(0, 6.28), rnd.uniform(1.5, 3)) for _ in range(20)]

    def draw(self, f, t, T):
        x, y = 540, CONTENT_Y + 40
        r = lerp(150, 90, ease(t / T))
        black_hole(f, x, y, r, t, particles=[(R * r / 150, a, s) for R, a, s in self.parts], alpha=1)
        for a, ph in self.pairs:
            u = (t / 1.4 + ph) % 1
            ex = r * 1.15 + 420 * u
            f.circle(x + ex * math.cos(a), y + ex * math.sin(a) * 0.8, 6 * (1 - u) + 2,
                     fill=(150, 230, 255), a=1 - u)
            if u < 0.35:
                inn = r * 1.15 - 50 * u / 0.35
                f.circle(x + inn * math.cos(a), y + inn * math.sin(a) * 0.8, 5,
                         fill=(255, 150, 90), a=1 - u / 0.35)


class Zeros:
    """Il conto alla rovescia più lungo: 10^67 anni."""

    def __init__(self, rnd):
        self.sf = None

    def draw(self, f, t, T):
        x, y = 540, CONTENT_Y - 10
        n = int(round(67 * ease(min(t / (T * 0.7), 1))))
        base = text_sprite("10", 230, (255, 255, 255), 10)
        exp = text_sprite(str(n), 130, (255, 200, 40), 8)
        f.paste(base, x - 60, y)
        f.paste(exp, x + 60 + exp.width / 2 - 10, y - 110, scale=1 + 0.08 * math.sin(t * 20) * (n < 67))
        f.paste(text_sprite("ANNI", 90, (170, 225, 255), 7), x, y + 190)
        zeros = "0" * min(n, 67)
        txt = "1" + zeros
        rows = [txt[i:i + 17] for i in range(0, len(txt), 17)]
        for k, rw in enumerate(rows):
            f.paste(text_sprite(rw, 50, (210, 210, 240), 4), x, y + 300 + k * 60, opacity=0.9)
        black_hole(f, x, y - 330, 34 * (1 - 0.5 * ease(t / T)), t, glow=True)


ANIMS = {
    "spaghetti": Spaghetti, "accretion": Accretion, "light_bend": LightBend, "stretch": Stretch,
    "clocks": Clocks, "galaxy": Galaxy, "first_photo": FirstPhoto, "hawking": Hawking, "zeros": Zeros,
}


def _register_extra():
    from anim_atoms import ATOM_ANIMS          # scene di "Non hai mai toccato niente"
    ANIMS.update(ATOM_ANIMS)


# ============================================================================ render di una scena

def background(c1, c2):
    sw, sh = 108, 192
    g = Image.new("RGB", (sw, sh))
    px = g.load()
    for yy in range(sh):
        for xx in range(sw):
            col = mixc(c1, c2, 0.75 * yy / sh + 0.25 * xx / sw)
            dx, dy = xx / sw - 0.5, yy / sh - 0.42
            v = 1 - 0.6 * min(1, dx * dx * 2.2 + dy * dy * 1.4)
            px[xx, yy] = tuple(int(c * v) for c in col)
    return g.resize((W, H), Image.BICUBIC)


def render_scene_frames(sc, idx, total, length, fps, write):
    """Genera i fotogrammi della scena e li passa a write(bytes_rgb)."""
    c1, c2 = (hex2rgb(x) for x in sc.get("colors", ["#05010f", "#2a0a4a"]))
    rnd = random.Random(1000 + idx)
    bg = background(c1, c2)
    stars = Starfield(rnd)
    if sc["anim"] not in ANIMS:
        _register_extra()
    anim = ANIMS[sc["anim"]](rnd)
    head = text_sprite(sc.get("headline", ""), 74, (255, 255, 255), 6, 940)
    nfr = int(math.ceil(length * fps))
    for k in range(nfr):
        t = k / fps
        f = Frame(bg)
        if sc.get("stars", True):
            stars.draw(f, t)
        anim.draw(f, t, length)
        if idx == 0:          # primo fotogramma = copertina nel feed: titolo già pieno
            f.paste(head, W / 2, 250)
        else:
            pop = 0.55 + 0.45 * ease_out_back(min(t / 0.35, 1))
            f.paste(head, W / 2, 250, scale=pop, opacity=min(1, 0.5 + t / 0.2))
        seg = 760 / total
        for j in (range(total) if sc.get("progress", True) else ()):
            x0 = 160 + j * seg
            fill = 1.0 if j < idx else (min(1, t / max(length, 0.1)) if j == idx else 0)
            f.ellipse((x0 + 4, 1780, x0 + seg - 4, 1792), fill=(255, 255, 255), a=0.25)
            if fill > 0:
                f.ellipse((x0 + 4, 1780, x0 + 4 + (seg - 8) * fill, 1792), fill=(255, 255, 255), a=0.95)
        f.flush()
        # camera: leggera spinta in avanti con piccola oscillazione
        z = 1.0 + 0.035 * ease(t / max(length, 0.1))
        if sc.get("punch") and idx > 0:          # "pugno" di zoom a inizio scena per tenere l'attenzione
            z += 0.09 * (1 - ease(t / 0.3))
        dx = 8 * math.sin(t * 0.9 + idx)
        a = 1 / z
        img = f.img.transform((W, H), Image.AFFINE,
                              (a, 0, W / 2 - a * W / 2 - dx * a, 0, a, H / 2 - a * H / 2), Image.BILINEAR)
        write(img.tobytes())
