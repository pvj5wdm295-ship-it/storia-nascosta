#!/usr/bin/env python3
"""
make_video.py - Genera uno YouTube Short (1080x1920, 30 fps) da un file argomento JSON.

Pipeline:
  1. voce narrante con edge-tts (una traccia per scena -> sincronizzazione esatta);
     se edge-tts non è raggiungibile ripiega sulla voce italiana offline Piper (scaricata in voices/)
  2. immagini delle scene con Pillow (gradiente, titolo, icona disegnata col codice)
  3. sottotitoli ASS grandi al centro, a gruppi di parole, tempi presi dal TTS
  4. montaggio ffmpeg: zoom leggero, dissolvenze incrociate, fade in/out, audio
  5. file .txt con titolo, descrizione e tag per YouTube

Uso:
  python make_video.py topics/stelle_di_neutroni.json --name short1
  python make_video.py --new-topic buchi_neri          # crea topics/buchi_neri.json da compilare
  python make_video.py topics/x.json --name prova --silent-test   # prova senza rete (audio muto)

Formato del JSON argomento:
  {
    "title": "...", "description": "...", "tags": ["..."],
    "voice": "it-IT-DiegoNeural", "rate": "+0%",
    "scenes": [
      {"text": "frase letta dalla voce (4-5 s)", "headline": "TESTO GRANDE",
       "icon": "star", "colors": ["#112233", "#445566"]}
    ]
  }
Icone disponibili: vedi ICONS in fondo al file.
"""

import argparse
import asyncio
import json
import math
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FPS = 30
S = 2                  # supersampling: si disegna a 2160x3840 (antialias + zoom senza scatti)
FADE = 0.5             # durata dissolvenza tra scene (s)
PAUSE = 0.30           # pausa dopo ogni frase (s)
WORDS_PER_SUB = 3      # parole per riga di sottotitolo
ICON_Y = 700           # centro verticale dell'icona (le icone stanno entro ±340 px)
SUB_Y = 1330           # centro verticale dei sottotitoli
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
ROOT = Path(__file__).resolve().parent


# ----------------------------------------------------------------------------- utilità

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        raise SystemExit(f"Comando fallito: {' '.join(map(str, cmd[:6]))} ...")
    return r.stdout


def media_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# ----------------------------------------------------------------------------- 1. voce

def _ssl_context():
    """Usa il bundle CA indicato dall'ambiente (es. proxy aziendale), altrimenti certifi."""
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        if os.environ.get(var) and Path(os.environ[var]).exists():
            return ssl.create_default_context(cafile=os.environ[var])
    return None


async def _tts_scene(text, voice, rate, mp3_path):
    import edge_tts
    ctx = _ssl_context()
    if ctx is not None:  # edge-tts usa certifi di default: lo sostituiamo se serve
        import edge_tts.communicate as ec
        ec._SSL_CTX = ctx
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary", proxy=proxy)
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"w": chunk["text"], "start": start,
                              "end": start + chunk["duration"] / 1e7})
    return words


PIPER_MODEL = "it-riccardo_fasol-x-low"
PIPER_URL = ("https://github.com/rhasspy/piper/releases/download/v0.0.2/"
             "voice-it-riccardo_fasol-x-low.tar.gz")
VOICES_DIR = ROOT / "voices"


def piper_model():
    """Scarica (una volta sola) la voce italiana offline di Piper in voices/."""
    onnx = VOICES_DIR / f"{PIPER_MODEL}.onnx"
    if not onnx.exists():
        import tarfile
        import urllib.request
        VOICES_DIR.mkdir(exist_ok=True)
        tgz = VOICES_DIR / "voice.tar.gz"
        print(f"  scarico la voce Piper ({PIPER_MODEL})…")
        urllib.request.urlretrieve(PIPER_URL, tgz)
        with tarfile.open(tgz) as t:
            t.extractall(VOICES_DIR, filter="data")
        tgz.unlink()
    return onnx


KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


def kokoro_model():
    """Scarica (una volta sola) Kokoro-82M (Apache 2.0) in voices/kokoro/ e lo carica."""
    import urllib.request
    from kokoro_onnx import Kokoro
    d = VOICES_DIR / "kokoro"
    d.mkdir(parents=True, exist_ok=True)
    for name in KOKORO_FILES:
        if not (d / name).exists():
            print(f"  scarico {name} (Kokoro)…")
            urllib.request.urlretrieve(KOKORO_URL + name, d / name)
    return Kokoro(str(d / KOKORO_FILES[0]), str(d / KOKORO_FILES[1]))


def _kokoro_scene(model, text, voice, speed, wav):
    import soundfile as sf
    # fonemi italiani via espeak; si tolgono i marcatori di cambio lingua tipo "(en)…(it)"
    ph = re.sub(r"\((?:[a-z]{2}(?:-[a-z]+)?)\)", "", model.tokenizer.phonemize(text, "it"))
    audio, sr = model.create(ph, voice=voice, speed=speed, is_phonemes=True)
    raw = wav.with_suffix(".raw.wav")
    sf.write(str(raw), audio, sr)
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
    run(["ffmpeg", "-y", "-i", raw, "-af", f"{trim},aresample=48000,highpass=f=60", "-ac", "2", wav])


def _speech_bounds(wav, dur):
    """Inizio e fine del parlato (salta silenzi iniziali/finali) via silencedetect."""
    r = subprocess.run(["ffmpeg", "-i", str(wav), "-af", "silencedetect=n=-35dB:d=0.08",
                        "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    t0 = ends[0] if starts and starts[0] < 0.02 and ends else 0.0
    t1 = starts[-1] if starts and starts[-1] > dur - 0.6 and starts[-1] > t0 else dur
    return t0, t1


def estimate_words(text, t0, t1):
    """Tempi parola stimati in proporzione alla lunghezza (per motori senza WordBoundary)."""
    toks = text.split()
    weights = [len(re.sub(r"\W", "", w)) + 2 + (4 if re.search(r"[,.;:!?]$", w) else 0) for w in toks]
    tot, acc, words = sum(weights), 0.0, []
    for w, k in zip(toks, weights):
        st = t0 + (t1 - t0) * acc / tot
        acc += k
        words.append({"w": w, "start": st, "end": t0 + (t1 - t0) * acc / tot})
    return words


def _piper_scene(voice, text, length_scale, wav):
    import wave
    from piper import SynthesisConfig
    raw = wav.with_suffix(".raw.wav")
    with wave.open(str(raw), "wb") as f:
        voice.synthesize_wav(text, f, syn_config=SynthesisConfig(length_scale=length_scale))
    # 16 kHz -> 48 kHz stereo, taglio dei bassi e un po' di presenza
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.06,areverse")
    run(["ffmpeg", "-y", "-i", raw, "-af",
         f"{trim},aresample=48000,highpass=f=70,equalizer=f=3500:t=q:w=1:g=3",
         "-ac", "2", wav])


# Catena voce (stessa di edit_v2.py --voice-polish): meno rimbombo e "scatola", più presenza e
# aria sopra gli 8 kHz, de-esser, compressione dolce, ambiente minimo. Attiva con "voice_polish".
VOICE_CHAIN = ("highpass=f=75,"
               "bass=g=1.5:f=140:w=0.7,"
               "equalizer=f=320:t=q:w=1.2:g=-2.5,"
               "equalizer=f=2800:t=q:w=1.0:g=2,"
               "aexciter=amount=1.2:drive=5:blend=0:freq=6500:ceil=16000,"
               "deesser=i=0.35:m=0.5:f=0.5,"
               "acompressor=threshold=-21dB:ratio=2.2:attack=10:release=150:makeup=1.5,"
               "aecho=1.0:1.0:19|31:0.05|0.035")


def synth_voice(scenes, voice, rate, work, engine="auto", polish=False, takes=1, target_wps=None,
                kokoro_voice="im_nicola"):
    """Restituisce per ogni scena: file wav (con pausa), durata, parole con tempi locali.

    engine: "edge" (edge-tts, online), "piper" (voce offline), "auto" (edge, e se non
    raggiungibile ripiega su piper per TUTTE le scene), "silent" (audio muto di prova).
    """
    out, piper_voice, kokoro = [], None, None
    # rate edge-tts "+5%" -> length_scale piper 1/1.05
    length_scale = 1 / (1 + int(re.sub(r"[^\d-]", "", rate) or 0) / 100)
    for i, sc in enumerate(scenes):
        wav = work / f"voice_{i:02d}.wav"
        words = None
        if engine == "silent":
            words_txt = sc["text"].split()
            dur = max(2.0, len(words_txt) / 2.7)
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                 "-t", f"{dur:.3f}", wav])
            words = estimate_words(sc["text"], 0, dur)
        if engine in ("edge", "auto"):
            mp3 = work / f"voice_{i:02d}.mp3"
            try:
                words = asyncio.run(_tts_scene(sc["text"], voice, rate, mp3))
                run(["ffmpeg", "-y", "-i", mp3, "-ar", "48000", "-ac", "2", wav])
                dur = media_duration(wav)
            except Exception as e:  # rete bloccata, servizio giù, ecc.
                if engine == "edge" or i > 0:
                    raise SystemExit(f"edge-tts non disponibile: {e}")
                try:
                    kokoro = kokoro_model()
                    engine = "kokoro"
                except Exception as e2:  # modello non scaricabile: ultima risorsa Piper
                    print(f"  Kokoro non disponibile ({type(e2).__name__}): uso Piper")
                    engine = "piper"
                print(f"  edge-tts non raggiungibile ({type(e).__name__}): uso la voce offline {engine}")
        if engine == "kokoro":
            if kokoro is None:
                kokoro = kokoro_model()
            speed = 1 + int(re.sub(r"[^\d-]", "", rate) or 0) / 100
            _kokoro_scene(kokoro, sc["text"], kokoro_voice, speed, wav)
            dur = media_duration(wav)
            words = estimate_words(sc["text"], *_speech_bounds(wav, dur))
        if engine == "piper":
            if piper_voice is None:
                from piper import PiperVoice
                piper_voice = PiperVoice.load(piper_model())
            # Piper varia la durata a ogni generazione: si registrano più "prese" e si tiene
            # quella più vicina al ritmo obiettivo (parole al secondo)
            nw = len(sc["text"].split())
            best, ls = None, length_scale
            for k in range(max(1, takes)):
                take = wav.with_name(f"{wav.stem}_take{k}.wav")
                _piper_scene(piper_voice, sc["text"], ls, take)
                d = media_duration(take)
                score = abs(nw / d - target_wps) if target_wps else 0
                if best is None or score < best[0]:
                    best = (score, take, d)
                if not target_wps or score < 0.08:
                    break
                ls = min(1.6, max(0.8, ls * (nw / d) / target_wps))   # corregge la presa successiva
            best[1].replace(wav)
            dur = media_duration(wav)
            words = estimate_words(sc["text"], *_speech_bounds(wav, dur))
        if polish and engine != "silent":
            tmp = wav.with_suffix(".polish.wav")
            run(["ffmpeg", "-y", "-i", wav, "-af", VOICE_CHAIN, "-ar", "48000", "-ac", "2", tmp])
            tmp.replace(wav)
        words = attach_punctuation(sc["text"], words)
        out.append({"wav": wav, "dur": dur + PAUSE, "speech": dur, "words": words})
        print(f"  scena {i + 1}: {dur:.2f}s  «{sc['text'][:50]}…»")
    return out, engine


def attach_punctuation(text, words):
    """Le WordBoundary non includono la punteggiatura: la ripristiniamo dal testo originale."""
    tokens = text.split()
    if len(tokens) == len(words):
        for w, t in zip(words, tokens):
            w["w"] = t
    return words


def build_audio(voices, work):
    lst = work / "voices.txt"
    padded = []
    for i, v in enumerate(voices):
        p = work / f"voice_pad_{i:02d}.wav"
        run(["ffmpeg", "-y", "-i", v["wav"], "-af", f"apad=whole_dur={v['dur']:.3f}", p])
        padded.append(p)
    lst.write_text("".join(f"file '{p.name}'\n" for p in padded))
    audio = work / "voice_full.wav"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy",
         audio.name], cwd=work)
    return audio


# ----------------------------------------------------------------------------- 2. immagini

def font(size):
    return ImageFont.truetype(FONT_BOLD, size * S)


class Canvas:
    """Wrapper di ImageDraw che lavora in coordinate 1080x1920 e disegna a risoluzione S×."""

    def __init__(self, img):
        self.img = img
        self.d = ImageDraw.Draw(img, "RGBA")

    @staticmethod
    def _p(pts):
        return [v * S for v in pts]

    def ellipse(self, box, **kw):
        if "width" in kw:
            kw["width"] = int(kw["width"] * S)
        self.d.ellipse(self._p(box), **kw)

    def circle(self, cx, cy, r, **kw):
        self.ellipse((cx - r, cy - r, cx + r, cy + r), **kw)

    def polygon(self, pts, **kw):
        if "width" in kw:
            kw["width"] = int(kw["width"] * S)
        self.d.polygon([(x * S, y * S) for x, y in pts], **kw)

    def line(self, pts, fill, width):
        self.d.line([(x * S, y * S) for x, y in pts], fill=fill, width=int(width * S), joint="curve")
        for x, y in (pts[0], pts[-1]):  # estremi arrotondati
            self.circle(x, y, width / 2, fill=fill)

    def rrect(self, box, r, **kw):
        if "width" in kw:
            kw["width"] = int(kw["width"] * S)
        self.d.rounded_rectangle(self._p(box), radius=r * S, **kw)

    def arc(self, box, start, end, fill, width):
        self.d.arc(self._p(box), start, end, fill=fill, width=int(width * S))


def gradient(c1, c2):
    """Gradiente diagonale + vignettatura, generato piccolo e poi scalato (veloce e liscio)."""
    sw, sh = 108, 192
    g = Image.new("RGB", (sw, sh))
    px = g.load()
    for y in range(sh):
        for x in range(sw):
            t = (0.75 * y / sh + 0.25 * x / sw)
            col = mix(c1, c2, t)
            # vignettatura morbida
            dx, dy = (x / sw - 0.5), (y / sh - 0.45)
            v = 1 - 0.55 * min(1, (dx * dx * 2.2 + dy * dy * 1.4))
            px[x, y] = tuple(int(c * v) for c in col)
    return g.resize((W * S, H * S), Image.BICUBIC)


def star_points(cx, cy, r_out, r_in, n=5, rot=-90):
    pts = []
    for k in range(n * 2):
        r = r_out if k % 2 == 0 else r_in
        a = math.radians(rot + k * 180 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw_sparkles(c, rnd, n=40):
    for _ in range(n):
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        r = rnd.choice([1.5, 2, 2.5, 3, 4])
        c.circle(x, y, r, fill=(255, 255, 255, rnd.randint(60, 200)))
    for _ in range(6):
        x, y = rnd.uniform(60, W - 60), rnd.uniform(60, H - 60)
        c.polygon(star_points(x, y, 14, 3, 4, 0), fill=(255, 255, 255, 170))


def draw_wrapped(c, text, cy, size, max_w=920, fill="white"):
    """Testo centrato, a capo automatico, con ombra."""
    f = font(size)
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if c.d.textlength(t, font=f) / S <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    lh = size * 1.15
    y0 = cy - lh * len(lines) / 2
    for k, ln in enumerate(lines):
        tw = c.d.textlength(ln, font=f) / S
        x, y = (W - tw) / 2, y0 + k * lh
        c.d.text(((x + 5) * S, (y + 6) * S), ln, font=f, fill=(0, 0, 0, 140))
        c.d.text((x * S, y * S), ln, font=f, fill=fill,
                 stroke_width=int(3 * S), stroke_fill=(0, 0, 0, 200))


def render_scene(sc, idx, total, path):
    c1, c2 = (hex2rgb(x) for x in sc.get("colors", ["#1a237e", "#00897b"]))
    img = gradient(c1, c2)
    c = Canvas(img)
    rnd = random.Random(idx * 7 + 3)
    draw_sparkles(c, rnd)

    # alone luminoso dietro l'icona
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy, r = 540 * S, ICON_Y * S, 330 * S
    gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=mix(c2, (255, 255, 255), 0.35) + (110,))
    glow = glow.filter(ImageFilter.GaussianBlur(70 * S))
    img.paste(glow, (0, 0), glow)
    c = Canvas(img)

    ICONS.get(sc.get("icon", ""), icon_default)(c, 540, ICON_Y, 1.0)

    # titolo in alto dentro una "pillola"
    draw_wrapped(c, sc.get("headline", ""), 250, 76)

    # indicatore di avanzamento in basso
    seg = 760 / total
    for k in (range(total) if sc.get("progress", True) else ()):
        x0 = 160 + k * seg
        col = (255, 255, 255, 230) if k <= idx else (255, 255, 255, 70)
        c.rrect((x0 + 4, 1780, x0 + seg - 4, 1792), 6, fill=col)

    img.convert("RGB").save(path)


# ----------------------------------------------------------------------------- icone
# Ogni icona: f(canvas, cx, cy, scala). Coordinate nello spazio 1080x1920.

WHITE = (255, 255, 255, 255)
GOLD = (255, 200, 40, 255)
INK = (20, 20, 40, 255)


def icon_default(c, x, y, s):
    c.circle(x, y, 200 * s, fill=(255, 255, 255, 60), outline=WHITE, width=12)
    draw_wrapped(c, "?", y - 10, 220)


def icon_star(c, x, y, s, r=230, col=(255, 236, 140, 255)):
    for k, a in enumerate((60, 35, 18)):
        c.circle(x, y, (r + 40 + k * 40) * s, fill=(255, 255, 255, a))
    c.polygon(star_points(x, y, r * s, r * 0.45 * s), fill=col, outline=WHITE, width=8)
    c.circle(x - 30, y - 10, 14, fill=INK)
    c.circle(x + 30, y - 10, 14, fill=INK)
    c.arc((x - 35, y - 5, x + 35, y + 45), 20, 160, fill=INK, width=8)


def icon_neutron_ball(c, x, y, r):
    c.circle(x, y, r + 30, fill=(140, 200, 255, 70))
    c.circle(x, y, r, fill=(170, 220, 255, 255), outline=WHITE, width=6)
    c.circle(x - r * 0.3, y - r * 0.3, r * 0.3, fill=(255, 255, 255, 160))


def icon_spoon_star(c, x, y, s):
    # bilancia: a sinistra un cucchiaino di stella di neutroni, a destra una folla. Vince il cucchiaino.
    c.polygon([(x, y - 60), (x - 70, y + 300), (x + 70, y + 300)], fill=(220, 220, 235, 255))
    c.rrect((x - 160, y + 290, x + 160, y + 330), 16, fill=(220, 220, 235, 255))
    tilt = math.radians(14)
    lx, ly = x - 300 * math.cos(tilt), y - 60 + 300 * math.sin(tilt)
    rx, ry = x + 300 * math.cos(tilt), y - 60 - 300 * math.sin(tilt)
    c.line([(lx, ly), (rx, ry)], fill=WHITE, width=22)
    c.circle(x, y - 60, 26, fill=GOLD)
    for px, py in ((lx, ly), (rx, ry)):
        c.line([(px, py), (px - 110, py + 170)], fill=(255, 255, 255, 200), width=6)
        c.line([(px, py), (px + 110, py + 170)], fill=(255, 255, 255, 200), width=6)
        c.d.chord([(px - 140) * S, (py + 110) * S, (px + 140) * S, (py + 230) * S], 0, 180, fill=(235, 235, 245, 255))
    # cucchiaino con la materia della stella
    c.line([(lx - 120, ly + 120), (lx - 10, ly + 155)], fill=(200, 200, 215, 255), width=18)
    c.ellipse((lx - 20, ly + 120, lx + 110, ly + 180), fill=(200, 200, 215, 255))
    icon_neutron_ball(c, lx + 45, ly + 120, 36)
    # folla stilizzata
    for row in range(3):
        for k in range(5 - row):
            px = rx - 100 + k * 50 + row * 25
            py = ry + 70 - row * 62
            c.circle(px, py - 10, 14, fill=WHITE)
            c.rrect((px - 15, py + 8, px + 15, py + 50), 10, fill=WHITE)
    draw_wrapped(c, "VINCE IL CUCCHIAINO!", y + 390, 44, fill=GOLD)


def icon_explosion(c, x, y, s):
    rnd = random.Random(5)
    pts = []
    for k in range(28):
        a = math.radians(k * 360 / 28)
        r = (300 if k % 2 == 0 else 170) + rnd.uniform(-30, 30)
        pts.append((x + r * math.cos(a), y + r * math.sin(a)))
    c.polygon(pts, fill=(255, 120, 30, 255), outline=(255, 220, 120, 255), width=10)
    inner = [(x + (px - x) * 0.6, y + (py - y) * 0.6) for px, py in pts]
    c.polygon(inner, fill=(255, 210, 60, 255))
    icon_neutron_ball(c, x, y, 70)
    for k in range(10):
        a = math.radians(k * 36 + 10)
        c.line([(x + 340 * math.cos(a), y + 340 * math.sin(a)),
                (x + 420 * math.cos(a), y + 420 * math.sin(a))], fill=(255, 230, 150, 230), width=14)


def icon_sun_squeeze(c, x, y, s):
    sx = x - 170
    for k in range(16):
        a = math.radians(k * 22.5)
        c.line([(sx + 200 * math.cos(a), y + 200 * math.sin(a)),
                (sx + 250 * math.cos(a), y + 250 * math.sin(a))], fill=(255, 210, 80, 255), width=16)
    c.circle(sx, y, 175, fill=(255, 180, 30, 255), outline=(255, 230, 120, 255), width=8)
    # freccia
    c.line([(x + 60, y), (x + 190, y)], fill=WHITE, width=24)
    c.polygon([(x + 230, y), (x + 180, y - 45), (x + 180, y + 45)], fill=WHITE)
    icon_neutron_ball(c, x + 300, y, 45)
    draw_wrapped(c, "20 km", y + 130, 54)


def icon_atom(c, x, y, s):
    orbit = (180, 230, 255, 255)
    for ang in (0, 60, 120):
        lay = Image.new("RGBA", (900 * S, 900 * S), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.ellipse((50 * S, 330 * S, 850 * S, 570 * S), outline=orbit, width=14 * S)
        lay = lay.rotate(ang, resample=Image.BICUBIC)
        c.img.paste(lay, ((x - 450) * S, (y - 450) * S), lay)
    c.d = ImageDraw.Draw(c.img, "RGBA")
    # nucleo: neutroni (grigio) + protoni (rosso)
    for k, (dx, dy) in enumerate([(-35, -25), (30, -30), (-5, 25), (40, 25), (-40, 30), (5, -60)]):
        col = (230, 70, 70, 255) if k % 3 == 0 else (190, 200, 215, 255)
        c.circle(x + dx, y + dy, 38, fill=col, outline=WHITE, width=4)
    for a in (20, 140, 260):
        r = math.radians(a)
        c.circle(x + 400 * math.cos(r) * 0.9, y + 120 * math.sin(r), 22, fill=(120, 255, 200, 255))


def icon_spin(c, x, y, s):
    icon_neutron_ball(c, x, y, 120)
    # fasci del pulsar
    c.polygon([(x - 25, y - 110), (x + 25, y - 110), (x + 110, y - 420), (x - 110, y - 420)], fill=(180, 230, 255, 120))
    c.polygon([(x - 25, y + 110), (x + 25, y + 110), (x + 110, y + 420), (x - 110, y + 420)], fill=(180, 230, 255, 120))
    for start in (200, 20):
        c.arc((x - 260, y - 260, x + 260, y + 260), start, start + 120, fill=WHITE, width=22)
        a = math.radians(start + 120)
        hx, hy = x + 260 * math.cos(a), y + 260 * math.sin(a)
        t = a + math.pi / 2
        c.polygon([(hx + 50 * math.cos(t), hy + 50 * math.sin(t)),
                   (hx + 40 * math.cos(t - 2.2), hy + 40 * math.sin(t - 2.2)),
                   (hx + 40 * math.cos(t + 2.2), hy + 40 * math.sin(t + 2.2))], fill=WHITE)


def icon_fall(c, x, y, s):
    # superficie della stella + metro + freccia
    c.d.chord([(x - 620) * S, (y + 200) * S, (x + 620) * S, (y + 560) * S], 180, 360, fill=(170, 220, 255, 255), outline=WHITE, width=8 * S)
    c.rrect((x - 300, y - 300, x - 250, y + 210), 10, fill=GOLD)
    for k in range(6):
        c.line([(x - 300, y - 300 + k * 100), (x - 270, y - 300 + k * 100)], fill=INK, width=6)
    draw_wrapped(c, "1 m", y - 360, 56)
    c.circle(x + 60, y - 260, 50, fill=WHITE)
    c.line([(x + 60, y - 180), (x + 60, y + 90)], fill=(255, 90, 90, 255), width=40)
    c.polygon([(x + 60, y + 170), (x - 10, y + 80), (x + 130, y + 80)], fill=(255, 90, 90, 255))
    for k in (-1, 1):
        c.line([(x + 60 + k * 110, y - 150), (x + 60 + k * 110, y + 20)], fill=(255, 255, 255, 150), width=10)


def icon_collision(c, x, y, s):
    for cx, sign in ((x - 200, 1), (x + 200, -1)):
        for k in range(1, 4):
            c.arc((cx - 120 - k * 45, y - 120 - k * 45, cx + 120 + k * 45, y + 120 + k * 45),
                  90 if sign > 0 else 270, 270 if sign > 0 else 450,
                  fill=(255, 255, 255, 140 - k * 30), width=8)
        icon_neutron_ball(c, cx, y, 110)
    c.polygon(star_points(x, y, 130, 50, 8, 0), fill=GOLD, outline=WHITE, width=6)


def icon_ring(c, x, y, s):
    c.circle(x, y + 70, 210, outline=GOLD, width=60)
    c.circle(x, y + 70, 240, outline=(255, 240, 170, 200), width=6)
    gem = [(x, y - 110), (x - 110, y - 210), (x - 60, y - 290), (x + 60, y - 290), (x + 110, y - 210)]
    c.polygon(gem, fill=(160, 230, 255, 255), outline=WHITE, width=8)
    c.polygon([(x, y - 110), (x - 60, y - 290), (x + 60, y - 290)], fill=(210, 245, 255, 255))
    for px, py in ((x - 300, y - 250), (x + 300, y - 200), (x + 260, y + 280)):
        c.polygon(star_points(px, py, 40, 10, 4, 0), fill=WHITE)


def icon_bell(c, x, y, s):
    c.circle(x, y - 270, 30, fill=GOLD)
    c.polygon([(x - 170, y + 120), (x - 140, y - 120), (x - 80, y - 220), (x, y - 245),
               (x + 80, y - 220), (x + 140, y - 120), (x + 170, y + 120)], fill=GOLD)
    c.rrect((x - 230, y + 100, x + 230, y + 160), 30, fill=GOLD)
    c.circle(x, y + 200, 50, fill=GOLD)
    for k in (-1, 1):
        c.arc((x - 330, y - 300, x + 330, y + 300), 180 + 30 if k < 0 else -30 - 30, 180 + 60 if k < 0 else -30 + 0,
              fill=WHITE, width=16)
    c.rrect((x - 230, y + 270, x + 230, y + 350), 40, fill=(230, 30, 50, 255))
    draw_wrapped(c, "ISCRIVITI", y + 305, 50)


def icon_bulb(c, x, y, s):
    c.circle(x, y - 60, 200, fill=(255, 235, 120, 255), outline=WHITE, width=10)
    c.rrect((x - 90, y + 120, x + 90, y + 260), 20, fill=(200, 200, 210, 255))
    for k in range(3):
        c.line([(x - 90, y + 160 + k * 40), (x + 90, y + 160 + k * 40)], fill=(120, 120, 140, 255), width=8)
    c.line([(x - 60, y - 40), (x, y + 40), (x + 60, y - 40)], fill=(230, 150, 20, 255), width=12)


def icon_planet(c, x, y, s):
    c.ellipse((x - 380, y - 90, x + 380, y + 90), outline=(255, 220, 160, 220), width=22)
    c.circle(x, y, 210, fill=(240, 160, 80, 255), outline=WHITE, width=8)
    c.ellipse((x - 180, y - 80, x - 20, y - 20), fill=(255, 200, 130, 200))
    c.arc((x - 380, y - 90, x + 380, y + 90), 0, 180, fill=(255, 220, 160, 255), width=22)


def icon_dna(c, x, y, s):
    for k in range(13):
        t = k / 12
        yy = y - 330 + t * 660
        dx = 160 * math.sin(t * math.pi * 2.5)
        c.line([(x - dx, yy), (x + dx, yy)], fill=(255, 255, 255, 180), width=10)
        c.circle(x - dx, yy, 26, fill=(90, 200, 255, 255))
        c.circle(x + dx, yy, 26, fill=(255, 110, 150, 255))


ICONS = {
    "star": icon_star, "spoon_star": icon_spoon_star, "explosion": icon_explosion,
    "sun_squeeze": icon_sun_squeeze, "atom": icon_atom, "spin": icon_spin, "fall": icon_fall,
    "collision": icon_collision, "ring": icon_ring, "bell": icon_bell, "bulb": icon_bulb,
    "planet": icon_planet, "dna": icon_dna, "default": icon_default,
}


# ----------------------------------------------------------------------------- 3. sottotitoli

def ass_time(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def build_subtitles(voices, path):
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,DejaVu Sans,92,&H00FFFFFF,&H0000E5FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,7,4,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines, t0 = [], 0.0
    for v in voices:
        ws = v["words"]
        for k in range(0, len(ws), WORDS_PER_SUB):
            grp = ws[k:k + WORDS_PER_SUB]
            start = t0 + grp[0]["start"]
            nxt = ws[k + WORDS_PER_SUB]["start"] if k + WORDS_PER_SUB < len(ws) else v["speech"] + 0.15
            end = t0 + nxt
            text = " ".join(w["w"] for w in grp).upper()
            # l'ultima parola del gruppo in giallo per dare ritmo; "pop" iniziale
            parts = text.split(" ")
            if len(parts) > 1:
                text = " ".join(parts[:-1]) + r" {\c&H00E5FF&}" + parts[-1]
            fx = r"{\pos(540,%d)\fscx80\fscy80\t(0,120,\fscx100\fscy100)}" % SUB_Y
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{fx}{text}")
        t0 += v["dur"]
    Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- 4. montaggio

def scene_length(voices, i):
    return voices[i]["dur"] + (FADE if i < len(voices) - 1 else 0)


def still_clip(png, i, length, path):
    """Scena fissa (immagine Pillow) con zoom lento alternato."""
    frames = int(math.ceil(length * FPS))
    z = f"1+0.10*on/{frames}" if i % 2 == 0 else f"1.10-0.10*on/{frames}"
    run(["ffmpeg", "-y", "-i", png, "-vf",
         f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
         f"setsar=1,format=yuv420p", "-frames:v", str(frames),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", path])


def anim_clip(args):
    """Scena animata: fotogrammi generati in Python e passati a ffmpeg via pipe."""
    sc, i, total, length, path = args
    import animations
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", str(path)],
                         stdin=subprocess.PIPE)
    animations.render_scene_frames(sc, i, total, length, FPS, p.stdin.write)
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit(f"ffmpeg fallito sulla scena {i + 1}")
    return path


def build_clips(scenes, voices, work):
    """Un clip video per scena: animato ("anim" nel JSON) oppure immagine fissa con zoom."""
    from concurrent.futures import ProcessPoolExecutor
    clips, jobs = [], []
    for i, sc in enumerate(scenes):
        clip = work / f"clip_{i:02d}.mp4"
        clips.append(clip)
        length = scene_length(voices, i)
        if sc.get("anim"):
            jobs.append((sc, i, len(scenes), length, clip))
        else:
            png = work / f"scene_{i:02d}.png"
            render_scene(sc, i, len(scenes), png)
            still_clip(png, i, length, clip)
    if jobs:
        with ProcessPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
            for path in ex.map(anim_clip, jobs):
                print(f"   {path.name} pronto")
    return clips


def write_wav(path, data, sr=48000):
    import wave
    import numpy as np
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    if pcm.ndim == 1:
        pcm = np.stack([pcm, pcm], axis=1)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(pcm.tobytes())


def synth_music(total, path, sr=48000):
    """Tappeto ambient generato col codice (nessun file esterno): accordi lenti + campanellini."""
    import numpy as np
    t = np.arange(int(total * sr)) / sr
    chords = [(55.0, 82.41, 130.81, 164.81), (49.0, 73.42, 123.47, 146.83),
              (43.65, 65.41, 110.0, 130.81), (41.2, 61.74, 98.0, 123.47)]
    out = np.zeros((len(t), 2))
    seg = 4.0
    for k in range(int(total / seg) + 2):
        st = k * seg - 1.0
        env = np.clip((t - st) / 1.5, 0, 1) * np.clip((st + seg + 2.0 - t) / 1.5, 0, 1)
        if not env.any():
            continue
        for j, fq in enumerate(chords[k % len(chords)]):
            for det, side in ((0.998, 0), (1.002, 1)):
                out[:, side] += env * np.sin(2 * np.pi * fq * det * t + j) * (0.5 if j < 2 else 0.3)
    rng = np.random.default_rng(3)
    for _ in range(int(total * 1.2)):
        st = rng.uniform(0, total)
        fq = rng.choice([880, 987.77, 1318.5, 1760])
        e = np.exp(-np.clip(t - st, 0, None) * 3) * (t >= st)
        pan = rng.uniform(0.2, 0.8)
        tone = 0.12 * e * np.sin(2 * np.pi * fq * t)
        out[:, 0] += tone * (1 - pan)
        out[:, 1] += tone * pan
    out /= np.max(np.abs(out)) + 1e-9
    write_wav(path, out * 0.5, sr)


def synth_whooshes(offsets, total, path, sr=48000):
    """Effetto "whoosh" (rumore filtrato con sweep) centrato su ogni transizione."""
    import numpy as np
    out = np.zeros(int((total + 1) * sr))
    rng = np.random.default_rng(7)
    L = int(0.7 * sr)
    for off in offsets:
        noise = rng.standard_normal(L)
        y, prev = np.zeros(L), 0.0
        for n in range(L):                               # passa-basso con taglio crescente
            a = 0.02 + 0.25 * (n / L) ** 1.5
            prev += a * (noise[n] - prev)
            y[n] = prev
        env = np.sin(np.pi * np.linspace(0, 1, L)) ** 2
        y = y * env / (np.max(np.abs(y)) + 1e-9)
        st = int(max(0, off - 0.35) * sr)
        out[st:st + L] += y[:len(out) - st]
    write_wav(path, out[:int(total * sr)] * 0.35, sr)


def assemble(clips, voices, audio, subs, out_path, work, topic):
    """Unisce i clip con le transizioni, imprime i sottotitoli e mixa voce, musica ed effetti.

    Opzioni dal JSON: "transitions" (lista di transizioni xfade, a rotazione), "fade_in",
    "fade_out" (default false), "music" ("synth" o percorso di un file audio), "music_db",
    "whoosh" (true/false), "whoosh_db".
    """
    n = len(clips)
    total = sum(v["dur"] for v in voices)
    trans = topic.get("transitions") or ["fade"]
    cmd = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", c.name]
    cmd += ["-i", audio.name]
    fc, prev, offset, offsets = [], "0:v", 0.0, []
    for i in range(1, n):
        offset += voices[i - 1]["dur"]
        offsets.append(offset + FADE / 2)
        tr = trans[(i - 1) % len(trans)]
        fc.append(f"[{prev}][{i}:v]xfade=transition={tr}:duration={FADE}:offset={offset:.3f}[x{i}]")
        prev = f"x{i}"
    vf = []
    if topic.get("fade_in", False):
        vf.append("fade=t=in:st=0:d=0.4")
    if topic.get("fade_out", False):
        vf.append(f"fade=t=out:st={total - 0.6:.3f}:d=0.6")
    vf.append(f"ass={subs.name}:fontsdir={FONT_DIR}")
    fc.append(f"[{prev}]" + ",".join(vf) + "[vout]")

    na = n + 1
    voice = f"[{n}:a]"
    mixes = []
    if topic.get("music"):
        mpath = work / "music.wav"
        if topic["music"] == "synth":
            synth_music(total, mpath)
        else:
            shutil.copy(ROOT / topic["music"], mpath)
        cmd += ["-stream_loop", "-1", "-i", mpath.name]
        gain = topic.get("music_db", -24)
        fc.append(f"{voice}asplit=2[vmain][vsc]")
        fc.append(f"[{na}:a]atrim=duration={total:.3f},volume={gain}dB,"
                  f"afade=t=out:st={max(0, total - 0.5):.3f}:d=0.5[mus]")
        fc.append("[mus][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=30:release=350[duck]")
        voice = "[vmain]"
        mixes.append("[duck]")
        na += 1
    if topic.get("whoosh") and offsets:
        wpath = work / "whoosh.wav"
        synth_whooshes(offsets, total, wpath)
        cmd += ["-i", wpath.name]
        fc.append(f"[{na}:a]volume={topic.get('whoosh_db', -12)}dB[wh]")
        mixes.append("[wh]")
        na += 1
    if mixes:
        fc.append(f"{voice}{''.join(mixes)}amix=inputs={1 + len(mixes)}:normalize=0:duration=first[mix]")
        voice = "[mix]"
    afx = ["loudnorm=I=-14:TP=-1.5"]
    if topic.get("fade_out", False):
        afx.insert(0, f"afade=t=out:st={total - 0.6:.3f}:d=0.6")
    fc.append(f"{voice}{','.join(afx)},aresample=48000[aout]")

    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{total:.3f}", "-movflags", "+faststart", str(Path(out_path).resolve())]
    run(cmd, cwd=work)


# ----------------------------------------------------------------------------- 5. metadati

def write_metadata(topic, path):
    tags = topic.get("tags", [])[:10]
    txt = (f"TITOLO:\n{topic['title']}\n\n"
           f"DESCRIZIONE:\n{topic['description']}\n\n"
           f"TAG ({len(tags)}):\n" + ", ".join(tags) + "\n")
    Path(path).write_text(txt, encoding="utf-8")


TEMPLATE = {
    "title": "Titolo accattivante #shorts",
    "description": "Descrizione del video.\n\n#scienza #curiosità #shorts",
    "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"],
    "engine": "kokoro",
    "kokoro_voice": "im_nicola",
    "voice": "it-IT-DiegoNeural",
    "rate": "+0%",
    "pause": 0.35,
    "music": "synth",
    "music_db": -20,
    "whoosh": True,
    "transitions": ["circleopen", "slideup", "zoomin", "smoothup", "radial", "dissolve"],
    "scenes": [
        {"text": "Prima frase: il gancio, circa dodici parole.", "headline": "GANCIO",
         "icon": "bulb", "colors": ["#1a0b3d", "#6a1b9a"]},
        {"text": "Seconda frase.", "headline": "TITOLO", "icon": "planet", "colors": ["#0d1b4c", "#1565c0"]},
    ],
}


# ----------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topic", nargs="?", help="file JSON dell'argomento (vedi topics/)")
    ap.add_argument("--name", default="short", help="nome base dei file in output/ (default: short)")
    ap.add_argument("--outdir", default=str(ROOT / "output"))
    ap.add_argument("--voice", help="voce edge-tts (sovrascrive quella del JSON)")
    ap.add_argument("--engine", choices=["auto", "edge", "kokoro", "piper"], default=None,
                    help="voce: edge-tts (online), kokoro o piper (offline); auto = edge, poi kokoro, poi piper")
    ap.add_argument("--silent-test", action="store_true",
                    help="niente TTS: audio muto con tempi stimati, solo per provare il montaggio")
    ap.add_argument("--keep-work", action="store_true", help="non cancellare la cartella temporanea")
    ap.add_argument("--new-topic", metavar="NOME", help="crea topics/NOME.json da compilare ed esce")
    a = ap.parse_args()

    if a.new_topic:
        p = ROOT / "topics" / f"{a.new_topic}.json"
        p.parent.mkdir(exist_ok=True)
        if p.exists():
            raise SystemExit(f"{p} esiste già")
        p.write_text(json.dumps(TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Creato {p}: compila testo e scene, poi lancia python make_video.py {p} --name ...")
        return
    if not a.topic:
        ap.error("serve il file JSON dell'argomento (oppure --new-topic NOME)")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} non trovato: installalo (es. apt install ffmpeg)")

    topic = json.loads(Path(a.topic).read_text(encoding="utf-8"))
    scenes = topic["scenes"]
    for sc in scenes:                            # opzioni globali che valgono per ogni scena
        sc.setdefault("progress", bool(topic.get("progress_bar", True)))
        sc.setdefault("punch", bool(topic.get("punch", False)))
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    work = outdir / f".work_{a.name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    global PAUSE
    PAUSE = float(topic.get("pause", PAUSE))     # pausa dopo ogni frase, configurabile dal JSON
    print("1/5 voce narrante…")
    engine = "silent" if a.silent_test else (a.engine or topic.get("engine", "auto"))
    voices, engine = synth_voice(scenes, a.voice or topic.get("voice", "it-IT-DiegoNeural"),
                                 topic.get("rate", "+0%"), work, engine=engine,
                                 polish=bool(topic.get("voice_polish")),
                                 takes=int(topic.get("voice_takes", 1)),
                                 target_wps=topic.get("target_wps"),
                                 kokoro_voice=topic.get("kokoro_voice", "im_nicola"))
    print(f"   motore voce: {engine}")
    audio = build_audio(voices, work)
    total = sum(v["dur"] for v in voices)
    print(f"   durata totale: {total:.1f}s")

    print("2/5 scene (immagini e animazioni)…")
    clips = build_clips(scenes, voices, work)

    print("3/5 sottotitoli…")
    subs = work / "subs.ass"
    build_subtitles(voices, subs)

    print("4/5 montaggio ffmpeg…")
    mp4 = outdir / f"{a.name}.mp4"
    assemble(clips, voices, audio, subs, mp4, work, topic)

    print("5/5 metadati YouTube…")
    write_metadata(topic, outdir / f"{a.name}.txt")

    if not a.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    print(f"Fatto: {mp4} ({media_duration(mp4):.1f}s) e {outdir / (a.name + '.txt')}")


if __name__ == "__main__":
    main()
