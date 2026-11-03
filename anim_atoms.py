"""
anim_atoms.py - Scene animate per "Non hai mai toccato niente" (atomi, vuoto, polvere di stelle).

Stesso schema di animations.py: ogni classe ha __init__(rnd) e draw(f, t, T) e si registra in
ATOM_ANIMS, che animations.py aggiunge ad ANIMS.
"""
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from animations import (CONTENT_Y, W, H, Frame, arrow, ease, ease_out_back, glow_sprite, lerp, mixc,
                        text_sprite)

BLUE = (110, 190, 255)
CLOUD = (90, 160, 255)
RED = (255, 90, 90)
SKIN = (240, 190, 150)
GOLD = (255, 210, 110)


# ============================================================================ elementi comuni

def nucleus(f, x, y, r, t, n=7):
    """Nucleo: protoni (rossi) e neutroni (grigi) impacchettati, con un leggero tremolio."""
    f.paste(glow_sprite(int(r * 1.6), (255, 150, 120), 120), x, y)
    for k in range(n):
        a = k * 2.399 + 0.3
        d = r * 0.55 * math.sqrt(k / n)
        jx, jy = 2 * math.sin(t * 9 + k), 2 * math.cos(t * 11 + k)
        col = (235, 80, 80) if k % 2 == 0 else (200, 200, 215)
        f.circle(x + d * math.cos(a) + jx, y + d * math.sin(a) + jy, r * 0.42, fill=col,
                 outline=(40, 20, 30), width=2, oa=0.5)


def electron_cloud(f, x, y, R, t, alpha=1.0, n_e=3, tilt=0.38, nuc=True, speed=1.0, sign=True):
    """Atomo: nuvola di elettroni + orbite inclinate + nucleo al centro."""
    f.paste(glow_sprite(int(R), CLOUD, int(70 * alpha)), x, y)
    orbits = [(R, tilt, a) for a in (0, 60, 120)][:n_e]
    for k, (rr, ti, rot) in enumerate(orbits):
        th = math.radians(rot)
        pts = []
        for s in range(0, 361, 10):
            u = math.radians(s)
            ox, oy = rr * math.cos(u), rr * ti * math.sin(u)
            pts.append((x + ox * math.cos(th) - oy * math.sin(th), y + ox * math.sin(th) + oy * math.cos(th)))
        f.line(pts, (150, 200, 255), 3, a=0.35 * alpha)
    if nuc:
        nucleus(f, x, y, max(8, R * 0.12), t)
    for k, (rr, ti, rot) in enumerate(orbits):
        th = math.radians(rot)
        u = t * speed * (2.6 + 0.4 * k) + k * 2.1
        ox, oy = rr * math.cos(u), rr * ti * math.sin(u)
        ex, ey = x + ox * math.cos(th) - oy * math.sin(th), y + ox * math.sin(th) + oy * math.cos(th)
        f.paste(glow_sprite(max(6, int(R * 0.09)), BLUE, int(180 * alpha)), ex, ey)
        f.circle(ex, ey, max(5, R * 0.055), fill=(220, 240, 255), a=alpha)
        if sign and R > 120:
            f.paste(text_sprite("−", 34, (255, 255, 255), 3), ex, ey - 3, opacity=alpha)


@lru_cache(maxsize=4)
def finger_sprite(length=520, thick=120):
    """Indice stilizzato, orizzontale, punta verso destra (RGBA)."""
    s = 3
    im = Image.new("RGBA", (length * s, int(thick * 1.6) * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cy = im.height / 2
    th = thick * s
    d.rounded_rectangle((0, cy - th / 2, length * s, cy + th / 2), radius=th / 2, fill=SKIN + (255,))
    d.rounded_rectangle((0, cy - th / 2, length * s * 0.35, cy + th * 0.8), radius=th / 3, fill=SKIN + (255,))
    for k in (0.45, 0.68):                                   # pieghe delle falangi
        x = length * s * k
        d.arc((x - th * 0.25, cy - th * 0.35, x + th * 0.25, cy + th * 0.35), 100, 260,
              fill=(200, 140, 110, 255), width=3 * s)
    nx = length * s - th * 0.95                              # unghia
    d.rounded_rectangle((nx, cy - th * 0.42, nx + th * 0.72, cy + th * 0.02), radius=th * 0.2,
                        fill=(255, 225, 215, 255))
    return im.resize((length, int(thick * 1.6)), Image.LANCZOS)


def lens(f, x, y, R, draw_inside, t, label=None):
    """Lente d'ingrandimento: disegna draw_inside(f, cx, cy, R) e poi la cornice."""
    R = int(R)
    sub = Frame(Image.new("RGB", (2 * R, 2 * R), (8, 12, 30)))
    draw_inside(sub, R, R, R, t)                            # disegno ritagliato dentro il vetro
    sub.flush()
    k = 3
    mask = Image.new("L", (2 * R * k, 2 * R * k), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 2 * R * k, 2 * R * k), fill=255)
    sp = sub.img.convert("RGBA")
    sp.putalpha(mask.resize((2 * R, 2 * R), Image.LANCZOS))
    f.paste(sp, x, y)
    f.circle(x, y, R, outline=(240, 240, 255), width=12)
    a = math.radians(45)
    f.line([(x + R * math.cos(a), y + R * math.sin(a)), (x + (R + 90) * math.cos(a), y + (R + 90) * math.sin(a))],
           (240, 240, 255), 24)
    if label:
        f.paste(text_sprite(label, 34, (200, 230, 255), 4), x, y + R * 0.66)


def person(f, x, y, s, col=(120, 200, 255), a=1.0):
    """Omino stilizzato (testa + corpo) alto ~s*2.4, piedi in (x, y)."""
    f.circle(x, y - s * 2.1, s * 0.32, fill=col, a=a)
    f.polygon([(x - s * 0.42, y - s * 1.7), (x + s * 0.42, y - s * 1.7), (x + s * 0.3, y - s * 0.75),
               (x - s * 0.3, y - s * 0.75)], col, a)
    f.line([(x - s * 0.15, y - s * 0.8), (x - s * 0.22, y)], col, max(2, s * 0.18), a)
    f.line([(x + s * 0.15, y - s * 0.8), (x + s * 0.22, y)], col, max(2, s * 0.18), a)


# ============================================================================ scene

class Touch:
    """Gancio: il dito si avvicina a una mela ma si ferma prima; la lente mostra il vuoto in mezzo."""

    def __init__(self, rnd):
        self.sparks = [(rnd.uniform(-1, 1), rnd.uniform(0, 1)) for _ in range(14)]

    def draw(self, f, t, T):
        ax, ay, ar = 760, CONTENT_Y - 80, 170
        u = ease(min(t / (T * 0.35), 1))
        tip = lerp(80, ax - ar - 14, u)                        # punta del dito: si ferma a un soffio
        fs = finger_sprite()
        f.paste(fs, tip - fs.width / 2, ay + 15)
        # mela
        f.paste(glow_sprite(ar, (255, 80, 80), 60), ax, ay)
        f.circle(ax - 40, ay, ar * 0.92, fill=(210, 30, 45))
        f.circle(ax + 40, ay, ar * 0.92, fill=(210, 30, 45))
        f.circle(ax - 70, ay - 60, 40, fill=(255, 140, 140), a=0.55)
        f.line([(ax, ay - ar * 0.85), (ax + 15, ay - ar * 1.2)], (110, 70, 40), 14)
        f.ellipse((ax + 20, ay - ar * 1.3, ax + 110, ay - ar * 1.05), fill=(80, 190, 90))
        if u >= 1:
            g = ease((t - T * 0.35) / 0.4)
            for sx, ph in self.sparks:
                p = (t * 2.2 + ph) % 1
                f.circle(ax - ar - 7 - 40 * p * (1 if sx > 0 else -1) * 0.3, ay + 15 + sx * 60,
                         4 + 4 * (1 - p), fill=(170, 225, 255), a=g * (1 - p))
            if g > 0:
                def inside(f, cx, cy, R, t):
                    gap = 60 + 6 * math.sin(t * 7)
                    electron_cloud(f, cx - gap / 2 - 85, cy, 110, t, nuc=False, n_e=2, sign=False)
                    electron_cloud(f, cx + gap / 2 + 85, cy, 110, t + 1, nuc=False, n_e=2, sign=False)
                    arrow(f, cx - 12, cy, cx - 110, cy, RED, 12)
                    arrow(f, cx + 12, cy, cx + 110, cy, RED, 12)
                s = ease_out_back(g)
                lx, ly, R = 540, CONTENT_Y + 310, 210 * s
                if R > 20:
                    lens(f, lx, ly, R, inside, t, "× 100 milioni" if s > 0.95 else None)
                    f.line([(ax - ar - 7, ay + 15), (lx - R * 0.7, ly - R * 0.7)], (240, 240, 255), 3, a=0.5)


class AtomCloud:
    """Un atomo grande: nucleo al centro, tre elettroni negativi che girano."""

    def draw(self, f, t, T):
        s = ease_out_back(min(t / 0.6, 1))
        electron_cloud(f, 540, CONTENT_Y + 30, 360 * max(s, 0.05), t, speed=1.2)
        if t > 0.8:
            o = ease((t - 0.8) / 0.4)
            f.paste(text_sprite("nucleo", 40, (255, 190, 170), 4), 540, CONTENT_Y + 130, opacity=o)
            f.paste(text_sprite("elettroni = carica −", 46, (170, 225, 255), 4), 540, CONTENT_Y + 470, opacity=o)

    def __init__(self, rnd):
        pass


class Repel:
    """Due atomi si avvicinano e rimbalzano: le nuvole negative si respingono."""

    def __init__(self, rnd):
        pass

    def draw(self, f, t, T):
        y, R = CONTENT_Y + 30, 210
        # avvicinamento, poi oscillazione smorzata attorno a una distanza minima
        u = min(t / 1.4, 1)
        d0, dmin = 900, 2 * R + 60
        if t < 1.4:
            d = lerp(d0, dmin, ease(u))
        else:
            d = dmin + 90 * math.exp(-(t - 1.4) * 1.6) * abs(math.sin((t - 1.4) * 5))
        electron_cloud(f, 540 - d / 2, y, R, t)
        electron_cloud(f, 540 + d / 2, y, R, t + 1.3)
        if t > 1.0:
            g = ease((t - 1.0) / 0.4)
            f.paste(glow_sprite(90, (255, 80, 80), int(150 * g * (0.6 + 0.4 * math.sin(t * 9)))), 540, y)
            wob = 14 * math.sin(t * 8)
            arrow(f, 520, y - R - 50, 340 - wob, y - R - 50, RED, 16, a=g)
            arrow(f, 560, y - R - 50, 740 + wob, y - R - 50, RED, 16, a=g)
            f.paste(text_sprite("−  respinge  −", 50, (255, 160, 160), 5), 540, y + R + 110, opacity=g)


class Floating:
    """Sei seduto ma stai "fluttuando": la lente mostra la fila di atomi tuoi sopra quelli della sedia."""

    def __init__(self, rnd):
        pass

    def draw(self, f, t, T):
        x, y = 360, CONTENT_Y + 40
        bob = 3 * math.sin(t * 3)
        wood = (170, 115, 70)
        f.line([(x - 140, y), (x + 150, y)], wood, 26)                                  # seduta
        f.line([(x - 130, y), (x - 130, y + 260)], wood, 20)
        f.line([(x + 140, y), (x + 140, y + 260)], wood, 20)
        f.line([(x - 140, y), (x - 160, y - 300)], wood, 22)                           # schienale
        col = (120, 200, 255)
        f.circle(x - 40, y - 330 + bob, 62, fill=col)                                  # testa
        f.polygon([(x - 120, y - 250 + bob), (x + 20, y - 250 + bob), (x + 40, y - 18 + bob),
                   (x - 110, y - 18 + bob)], col)                                       # busto
        f.line([(x - 20, y - 40 + bob), (x + 190, y - 40 + bob)], col, 56)            # cosce
        f.line([(x + 190, y - 40 + bob), (x + 200, y + 250)], col, 50)                # gambe
        f.line([(x - 20, y - 180 + bob), (x + 120, y - 110 + bob)], col, 36)          # braccio
        g = ease((t - 0.5) / 0.5)
        if g > 0:
            def inside(f, cx, cy, R, t):
                gap = 38 + 10 * math.sin(t * 6)
                for k in range(-3, 4):
                    f.circle(cx + k * 64, cy - gap / 2 - 34, 30, fill=col, a=0.9)
                    f.circle(cx + k * 64, cy + gap / 2 + 34, 30, fill=wood, a=0.95)
                for k in (-2, 0, 2):
                    arrow(f, cx + k * 64 + 32, cy - 6, cx + k * 64 + 32, cy - 40, RED, 6)
                    arrow(f, cx + k * 64 + 32, cy + 6, cx + k * 64 + 32, cy + 40, RED, 6)
                f.paste(text_sprite("tu", 38, (190, 230, 255), 4), cx, cy - 135)
                f.paste(text_sprite("sedia", 38, (230, 190, 150), 4), cx, cy + 135)
            s = ease_out_back(g)
            lx, ly, R = 790, CONTENT_Y - 180, 210 * s
            if R > 20:
                lens(f, lx, ly, R, inside, t)
                f.line([(x + 60, y - 10), (lx - R * 0.8, ly + R * 0.6)], (240, 240, 255), 3, a=0.5)


class Stadium:
    """Se il nucleo fosse una formica, l'atomo sarebbe uno stadio: zoom all'indietro."""

    def __init__(self, rnd):
        self.crowd = [(rnd.uniform(0, 6.28), rnd.uniform(0.88, 1.0)) for _ in range(260)]

    def draw(self, f, t, T):
        x, y = 540, CONTENT_Y + 40
        u = ease(min(max((t - 0.6) / (T * 0.55), 0), 1))
        s = lerp(5.0, 1.0, u)                     # da molto vicino allo stadio intero
        A, B = 440 * s, 300 * s
        f.ellipse((x - A, y - B, x + A, y + B), fill=(60, 70, 95))                      # spalti
        for a, rr in self.crowd:
            f.circle(x + A * rr * math.cos(a), y + B * rr * math.sin(a), 3 * s ** 0.5,
                     fill=(200, 200, 230), a=0.6)
        f.ellipse((x - A * 0.8, y - B * 0.75, x + A * 0.8, y + B * 0.75), fill=(40, 140, 70))  # campo
        f.ellipse((x - A * 0.8, y - B * 0.75, x + A * 0.8, y + B * 0.75), outline=(230, 255, 230), width=4)
        f.line([(x, y - B * 0.75), (x, y + B * 0.75)], (230, 255, 230), 4)
        f.circle(x, y, B * 0.2, outline=(230, 255, 230), width=4)
        for k in range(3):                                                              # elettroni sul bordo
            a = t * (1.6 + 0.3 * k) + k * 2.1
            ex, ey = x + A * 1.04 * math.cos(a), y + B * 1.04 * math.sin(a)
            f.paste(glow_sprite(18, BLUE, 200), ex, ey)
            f.circle(ex, ey, 9, fill=(220, 240, 255))
        # la formica (= nucleo) resta della stessa dimensione: piccolissima rispetto allo stadio
        k = 7
        f.circle(x + 4, y, k * 0.9, fill=(20, 15, 15))
        f.circle(x - 6, y, k * 0.7, fill=(20, 15, 15))
        f.circle(x + 13, y, k * 0.6, fill=(20, 15, 15))
        f.paste(glow_sprite(26, (255, 120, 90), 110), x, y)
        o = ease((t - 0.2) / 0.4)
        f.paste(text_sprite("nucleo = formica", 44, (255, 200, 170), 4), x, y - 70, opacity=o * (1 - u))
        o2 = ease((u - 0.7) / 0.3)
        if o2 > 0:
            f.paste(text_sprite("atomo = stadio", 52, (170, 225, 255), 5), x, y + B + 70, opacity=o2)
            f.paste(text_sprite("in mezzo: vuoto", 44, (230, 230, 240), 4), x, y - B - 60, opacity=o2)
        arrow(f, x + 140, y - 120, x + 22, y - 14, (255, 220, 120), 8, a=o)


class Sugar:
    """8 miliardi di persone: togli il vuoto e stanno in una zolletta di zucchero."""

    def __init__(self, rnd):
        self.people = []
        for i in range(17):
            for j in range(12):
                self.people.append((70 + i * 59 + rnd.uniform(-6, 6), 400 + j * 62 + rnd.uniform(-6, 6),
                                    rnd.uniform(0, 0.3), rnd.choice([(120, 200, 255), (255, 200, 120),
                                                                    (255, 150, 170), (160, 240, 170)])))

    def cube(self, f, x, y, s, a=1.0):
        top = [(x, y - s), (x + s, y - s * 0.5), (x, y), (x - s, y - s * 0.5)]
        left = [(x - s, y - s * 0.5), (x, y), (x, y + s), (x - s, y + s * 0.5)]
        right = [(x, y), (x + s, y - s * 0.5), (x + s, y + s * 0.5), (x, y + s)]
        f.polygon(left, (215, 215, 225), a)
        f.polygon(right, (240, 240, 248), a)
        f.polygon(top, (255, 255, 255), a)
        f.line(top + [top[0]], (190, 190, 205), 3, a)
        f.line([(x, y), (x, y + s)], (190, 190, 205), 3, a)

    def draw(self, f, t, T):
        cx, cy = 540, CONTENT_Y + 60
        u = ease(min(max((t - 0.9) / (T * 0.45), 0), 1))
        for px, py, dl, col in self.people:
            v = ease((u - dl) / (1 - dl)) if u > dl else 0
            if v >= 0.98:
                continue
            x, y = lerp(px, cx, v), lerp(py, cy, v)
            person(f, x, y + 20, 20 * (1 - 0.8 * v), col, a=1 - v * 0.6)
        g = ease((u - 0.55) / 0.45)
        if g > 0:
            f.paste(glow_sprite(120, (255, 255, 255), int(90 * g)), cx, cy)
            self.cube(f, cx, cy, 90 * ease_out_back(g), a=g)
            f.paste(text_sprite("≈ 2 cm³", 58, (255, 255, 255), 5), cx, cy + 190, opacity=g)
        o = 1 - ease((t - 0.9) / 0.5)
        if o > 0:
            f.paste(text_sprite("8 MILIARDI DI PERSONE", 56, (255, 220, 120), 5), cx, 1170, opacity=o)


class StarForge:
    """Dentro una stella: la fusione forgia carbonio e ossigeno, che volano fuori."""

    def __init__(self, rnd):
        self.parts = [(rnd.uniform(0, 6.28), rnd.uniform(0.1, 0.9), rnd.uniform(0.5, 2)) for _ in range(70)]
        self.atoms = [("C", (90, 90, 100), 0.2, -2.4), ("O", (90, 170, 255), 0.9, -0.7),
                      ("C", (90, 90, 100), 1.6, 0.6), ("O", (90, 170, 255), 2.3, 2.3),
                      ("N", (150, 120, 255), 2.9, 3.14)]

    def draw(self, f, t, T):
        x, y, R = 540, CONTENT_Y + 40, 260
        p = 1 + 0.03 * math.sin(t * 4)
        f.paste(glow_sprite(int(R * 1.6), (255, 170, 60), 150), x, y)
        f.circle(x, y, R * p, fill=(255, 160, 50))
        f.circle(x, y, R * 0.75 * p, fill=(255, 205, 90))
        f.circle(x, y, R * 0.45 * p, fill=(255, 245, 200))
        for a, rr, sp in self.parts:                      # nuclei che si scontrano nel cuore della stella
            aa = a + t * sp
            f.circle(x + R * rr * 0.6 * math.cos(aa), y + R * rr * 0.6 * math.sin(aa * 1.3), 4,
                     fill=(255, 255, 255), a=0.7)
        flash = (t * 1.5) % 1
        f.circle(x, y, 20 + 80 * flash, outline=(255, 255, 255), width=5, oa=1 - flash)
        for sym, col, t0, ang in self.atoms:
            u = (t - t0) / 1.6
            if u <= 0:
                continue
            u = min(u, 1)
            d = lerp(30, R + 170, ease(u))
            ax, ay = x + d * math.cos(ang), y + d * math.sin(ang)
            s = ease_out_back(min(u * 2, 1))
            f.circle(ax, ay, 52 * s, fill=col, outline=(255, 255, 255), width=5)
            f.paste(text_sprite(sym, 58, (255, 255, 255), 4), ax, ay - 4, scale=max(s, 0.05))


class Supernova:
    """Una stella esplode: il ferro viaggia nello spazio e finisce in una goccia di sangue."""

    def __init__(self, rnd):
        self.debris = [(rnd.uniform(0, 6.28), rnd.uniform(0.6, 1.2), rnd.uniform(3, 7)) for _ in range(110)]
        self.fe = [(-0.6 + 0.3 * k, 0.15 * k) for k in range(5)]

    def drop(self, f, x, y, s, a=1.0):
        f.circle(x, y + s * 0.3, s, fill=(200, 20, 40), a=a)
        f.polygon([(x - s * 0.82, y - s * 0.2), (x + s * 0.82, y - s * 0.2), (x, y - s * 1.5)], (200, 20, 40), a)
        f.circle(x - s * 0.35, y + s * 0.05, s * 0.22, fill=(255, 140, 150), a=a * 0.7)

    def draw(self, f, t, T):
        x, y = 540, CONTENT_Y - 160
        boom = 0.7
        if t < boom:
            r = lerp(120, 70, ease(t / boom)) + 6 * math.sin(t * 40)
            f.paste(glow_sprite(int(r * 1.8), (140, 170, 255), 160), x, y)
            f.circle(x, y, r, fill=(220, 230, 255))
        else:
            u = t - boom
            fl = math.exp(-u * 3)
            f.paste(glow_sprite(int(200 + 300 * (1 - fl)), (255, 230, 200), int(255 * fl)), x, y)
            ring = 120 + 700 * (1 - math.exp(-u * 1.4))
            f.circle(x, y, ring, outline=(255, 170, 120), width=14, oa=max(0, 0.8 - u * 0.3))
            f.circle(x, y, ring * 0.8, outline=(160, 200, 255), width=8, oa=max(0, 0.6 - u * 0.25))
            for a, sp, sz in self.debris:
                d = ring * sp
                f.circle(x + d * math.cos(a), y + d * math.sin(a), sz, fill=(255, 210, 160), a=max(0, 0.9 - u * 0.25))
            f.circle(x, y, 22, fill=(230, 240, 255), a=0.9)
        dx, dy = 540, CONTENT_Y + 280
        g = ease((t - 1.0) / 0.5)
        if g > 0:
            self.drop(f, dx, dy, 110 * ease_out_back(g), a=g)
            for ang, dl in self.fe:
                u = ((t - 1.0 - dl) / 1.6) % 1 if t > 1.0 + dl else -1
                if u < 0:
                    continue
                cx = lerp(x + 150 * math.sin(ang * 3), dx + 30 * ang, ease(u))
                cy = lerp(y + 80, dy, ease(u))
                o = 1 - ease((u - 0.8) / 0.2)
                f.circle(cx, cy, 34, fill=(170, 110, 80), outline=(255, 230, 200), width=4, a=o, oa=o)
                f.paste(text_sprite("Fe", 38, (255, 255, 255), 3), cx, cy - 3, opacity=o)
            f.paste(text_sprite("ferro nel sangue", 44, (255, 180, 180), 4), dx, dy + 150, opacity=g)


class Stardust:
    """Finale: una persona fatta di stelle che si ricompongono dal cielo."""

    def __init__(self, rnd):
        m = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(m)
        x, y = 540, CONTENT_Y + 120
        d.ellipse((x - 85, y - 430, x + 85, y - 260), fill=255)                      # testa
        d.rounded_rectangle((x - 150, y - 240, x + 150, y + 90), radius=70, fill=255)  # busto
        d.rounded_rectangle((x - 230, y - 220, x - 160, y + 60), radius=35, fill=255)  # braccia
        d.rounded_rectangle((x + 160, y - 220, x + 230, y + 60), radius=35, fill=255)
        d.rounded_rectangle((x - 130, y + 60, x - 20, y + 360), radius=45, fill=255)   # gambe
        d.rounded_rectangle((x + 20, y + 60, x + 130, y + 360), radius=45, fill=255)
        px = m.load()
        self.pts = []
        while len(self.pts) < 900:
            tx, ty = rnd.uniform(300, 780), rnd.uniform(y - 440, y + 370)
            if px[int(tx), int(ty)]:
                self.pts.append((rnd.uniform(-100, W + 100), rnd.uniform(-200, H * 0.4), tx, ty,
                                 rnd.uniform(0, 0.4), rnd.uniform(1.5, 4.2), rnd.uniform(0, 6.28),
                                 mixc((255, 240, 200), (150, 200, 255), rnd.random())))
        self.glow = m.resize((W // 4, H // 4)).filter(ImageFilter.GaussianBlur(14)).resize((W, H))

    def draw(self, f, t, T):
        u = ease(min(t / (T * 0.6), 1))
        g = ease((u - 0.6) / 0.4)
        if g > 0:
            sp = Image.new("RGBA", (W, H), (120, 170, 255, 0))
            sp.putalpha(self.glow.point(lambda v: int(v * 0.45 * g)))
            f.paste(sp, W / 2, H / 2)
        for sx, sy, tx, ty, dl, sz, ph, col in self.pts:
            v = ease((u - dl) / (1 - dl)) if u > dl else 0
            tw = 0.55 + 0.45 * math.sin(ph + t * 4)
            f.circle(lerp(sx, tx, v), lerp(sy, ty, v), sz, fill=col, a=0.4 + 0.6 * tw * (0.5 + 0.5 * v))


ATOM_ANIMS = {
    "touch": Touch, "atom_cloud": AtomCloud, "repel": Repel, "floating": Floating, "stadium": Stadium,
    "sugar": Sugar, "star_forge": StarForge, "supernova": Supernova, "stardust": Stardust,
}
