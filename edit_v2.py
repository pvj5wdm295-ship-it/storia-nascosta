#!/usr/bin/env python3
"""Rifinitura di un MP4 già generato (taglio finale, pause, primo frame, movimento, voce, loudnorm).

Uso:
  python edit_v2.py output/short1.mp4 output/short1_v2.mp4 /tmp/lavoro            # v2
  python edit_v2.py output/short1.mp4 output/short1_v3.mp4 /tmp/lavoro \\
      --pause 0.32 --tempo 0.88 --voice-polish                                      # v3

1. taglia il finale nella pausa che contiene END_NEAR (s), con 0,08 s di margine
2. porta a --pause secondi le pause di frase (silencedetect -35 dB, >=0,4 s), tagliando audio e
   video sugli stessi confini di frame e compensando lo zoom originale delle scene
3. sostituisce i frame della dissolvenza iniziale con un fermo immagine del primo frame pieno
4. aggiunge movimento leggero (zoom 1,01-1,06 e panoramica, fasi di ~1,8 s, con easing)
5. --tempo < 1 rallenta voce e video insieme (rubberband: durata più lunga, tono invariato),
   così i sottotitoli impressi restano sincronizzati
6. --voice-polish: catena voce (pulizia bassi, meno "scatola", presenza, aria, de-esser,
   compressione morbida, ambiente leggerissimo) per un suono meno sintetico
7. loudnorm a -14 LUFS in due passaggi, export H.264 + AAC 48 kHz

Nota: SPEECH contiene le durate del parlato di short1 (dal log di make_video.py) e serve
solo a ricostruire lo zoom originale; per un altro video vanno aggiornate.
"""
import argparse, json, math, os, re, subprocess
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("work")
ap.add_argument("--pause", type=float, default=0.18, help="pausa tra le frasi nel sorgente (s)")
ap.add_argument("--tempo", type=float, default=1.0, help="<1 rallenta (es. 0.88 = +14%% di durata)")
ap.add_argument("--voice-polish", action="store_true", help="catena di trattamento della voce")
args = ap.parse_args()
SRC, DST, WORK = args.src, args.dst, args.work
os.makedirs(WORK, exist_ok=True)
END_NEAR = 39.7   # secondo approssimativo in cui inizia la scena finale da eliminare
W, H, FPS = 1080, 1920, 30
FR = 1 / FPS
MARGIN, TARGET_PAUSE, TEMPO = 0.08, args.pause, args.tempo
ZMIN, ZMAX, SEG = 1.01, 1.06, 1.8
# durate del parlato per scena (log di make_video.py): servono a ricostruire lo zoom originale
SPEECH = [4.02, 3.60, 5.01, 4.27, 4.16, 3.63, 4.42, 4.13, 3.98, 5.42]
PAUSE_SRC, FADE_SRC = 0.30, 0.5

# Catena voce: taglio rimbombo, corpo, meno "scatola", presenza, aria sintetizzata sopra gli
# 8 kHz (il modello Piper x-low è a 16 kHz), de-esser, compressione dolce, stanza minima.
VOICE_CHAIN = ("highpass=f=75,"
               "bass=g=1.5:f=140:w=0.7,"
               "equalizer=f=320:t=q:w=1.2:g=-2.5,"
               "equalizer=f=2800:t=q:w=1.0:g=2,"
               "aexciter=amount=1.2:drive=5:blend=0:freq=6500:ceil=16000,"
               "deesser=i=0.35:m=0.5:f=0.5,"
               "acompressor=threshold=-21dB:ratio=2.2:attack=10:release=150:makeup=1.5,"
               "aecho=1.0:1.0:19|31:0.05|0.035")


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kw)


# ---------------------------------------------------------------- 1+2: tempi dei tagli
err = sh(["ffmpeg", "-hide_banner", "-i", SRC, "-vn", "-af", "silencedetect=n=-35dB:d=0.4",
          "-f", "null", "-"]).stderr
starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
sil = list(zip(starts, ends))
end_sil = next(p for p in sil if p[0] < END_NEAR < p[1] + 0.3)
end_frame = math.ceil((end_sil[0] + MARGIN) / FR + 1e-6)          # primo frame escluso
pauses = [p for p in sil if p[1] < end_sil[0]]

cuts = []  # (frame_inizio_rimosso, frame_fine_rimosso_esclusa)
for s, e in pauses:
    a = math.ceil((s + MARGIN) / FR - 1e-6)                        # griglia dei frame
    remove = math.floor(((e - s) - TARGET_PAUSE) / FR + 1e-6)      # frame interi da togliere
    while remove > 0 and (a + remove) * FR > e - MARGIN + 1e-6:
        remove -= 1
    if remove > 0:
        cuts.append((a, a + remove))

keep, cur = [], 0
for a, b in cuts:
    keep.append((cur, a))
    cur = b
keep.append((cur, end_frame))
frames = [f for a, b in keep for f in range(a, b)]                # timeline dopo i tagli

# ---------------------------------------------------------------- 3: primo frame pieno
out = sh(["ffprobe", "-v", "error", "-f", "lavfi", "-i",
          f"movie={SRC},trim=end_frame=40,signalstats", "-show_entries",
          "frame_tags=lavfi.signalstats.YAVG", "-of", "csv=p=0"]).stdout
yavg = [float(x.strip(",")) for x in out.split() if x.strip(",")]
ref = yavg[30]
first_full = next(i for i, y in enumerate(yavg) if y >= 0.985 * ref)

# ---------------------------------------------------------------- 5: rallentamento (mappa frame d'uscita -> frame tagliato)
n_cut = len(frames)
n_out = int(round(n_cut / TEMPO))
cut_index = [min(n_cut - 1, int(k * TEMPO + 0.5)) for k in range(n_out)]
dur_out = n_out / FPS

# ---------------------------------------------------------------- 4: movimento
nseg = max(1, round(dur_out / SEG))
seg_len = dur_out / nseg
PAN = (ZMAX - 1) * W / 2 * 0.6   # px di panoramica (resta dentro il margine dello zoom)


def ease(u):  # smoothstep a velocità nulla agli estremi: niente scatti
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def motion(t):
    """Sequenza: zoom in -> panoramica -> zoom out (con rientro) ... direzione alternata."""
    k = min(int(t / seg_len), nseg - 1)
    u = ease((t - k * seg_len) / seg_len)
    kind = k % 3
    side = 1 if (k // 3) % 2 == 0 else -1
    if kind == 0:
        return ZMIN + (ZMAX - ZMIN) * u, 0.0
    if kind == 1:
        return ZMAX, side * PAN * u
    return ZMAX - (ZMAX - ZMIN) * u, side * PAN * (1 - u)


def transform(img, z, dx):
    cx, cy = W / 2, H / 2
    a = 1 / z
    data = (a, 0, cx - a * cx - dx / z, 0, a, cy - a * cy)
    return img.transform((W, H), Image.AFFINE, data, resample=Image.BICUBIC)


# ---------------------------------------------------------------- compensazione dello zoom originale ai tagli
def z_src(f):
    off = 0.0
    for i, sp in enumerate(SPEECH):
        d = sp + PAUSE_SRC
        if f / FPS < off + d or i == len(SPEECH) - 1:
            n = math.ceil((d + (FADE_SRC if i < len(SPEECH) - 1 else 0)) * FPS)
            on = f - round(off * FPS)
            return 1 + 0.10 * on / n if i % 2 == 0 else 1.10 - 0.10 * on / n
        off += d


comp = [1.0] * n_cut                    # indicizzato sulla timeline tagliata
RAMP = 30
pos = 0
for (ka, kb), (ca, cb) in zip(keep, cuts):
    pos += kb - ka
    r = z_src(cb) / z_src(ca)
    for j in range(RAMP):
        comp[pos - RAMP + j] = r ** ease((j + 1) / RAMP)

# ---------------------------------------------------------------- video: decodifica -> elabora -> codifica
dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", SRC, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       stdout=subprocess.PIPE)
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-r", str(FPS), f"{WORK}/video.mp4"], stdin=subprocess.PIPE)
fsize = W * H * 3
idx, buf = -1, None
for k in range(n_out):
    j = cut_index[k]
    need = max(frames[j], first_full)    # i frame della dissolvenza iniziale -> fermo immagine
    while idx < need:
        buf = dec.stdout.read(fsize)
        idx += 1
    img = Image.frombuffer("RGB", (W, H), buf)
    z, dx = motion(k / FPS)
    enc.stdin.write(transform(img, z * comp[j], dx).tobytes())
dec.stdout.close(); dec.terminate()
enc.stdin.close(); enc.wait()

# ---------------------------------------------------------------- audio: stessi tagli, tempo, voce, loudnorm 2 passaggi
parts = "".join(f"[0:a]atrim=start={a * FR:.6f}:end={b * FR:.6f},asetpts=PTS-STARTPTS[a{i}];"
                for i, (a, b) in enumerate(keep))
post = []
if abs(TEMPO - 1) > 1e-6:
    post.append(f"rubberband=tempo={TEMPO}:pitchq=quality:transients=smooth:formant=preserved:"
                f"window=standard:channels=together")
post.append("aresample=48000")
if args.voice_polish:
    post.append(VOICE_CHAIN)
post.append(f"apad,atrim=duration={dur_out:.6f}")
fc = (parts + "".join(f"[a{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=0:a=1,"
      + ",".join(post) + "[out]")
sh(["ffmpeg", "-y", "-i", SRC, "-filter_complex", fc, "-map", "[out]", "-ar", "48000",
    "-c:a", "pcm_s16le", f"{WORK}/cut.wav"])
m = sh(["ffmpeg", "-hide_banner", "-i", f"{WORK}/cut.wav", "-af",
        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]).stderr
st = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
      f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:"
      f"offset={st['target_offset']}:linear=true,aresample=48000")
sh(["ffmpeg", "-y", "-i", f"{WORK}/video.mp4", "-i", f"{WORK}/cut.wav", "-af", ln,
    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
    "-t", f"{dur_out:.6f}", "-movflags", "+faststart", DST])

json.dump({"silences": sil, "end_frame": end_frame, "cuts_frames": cuts, "keep": keep,
           "first_full": first_full, "n_cut": n_cut, "n_out": n_out, "dur_out": dur_out,
           "tempo": TEMPO, "pause": TARGET_PAUSE, "voice_polish": args.voice_polish,
           "nseg": nseg, "seg_len": seg_len, "comp_min": min(comp), "comp_max": max(comp), "pan_px": PAN},
          open(f"{WORK}/report.json", "w"), indent=1)
print("ok", n_out, round(dur_out, 3))
