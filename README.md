# Video-short

Generatore di YouTube Shorts scientifici (1080x1920, 30 fps) interamente da codice:
voce `edge-tts` (it-IT-DiegoNeural), grafica Pillow, montaggio ffmpeg
(zoom leggero, dissolvenze, sottotitoli grandi al centro).

## Requisiti
```bash
sudo apt install ffmpeg          # oppure: brew install ffmpeg
pip install -r requirements.txt  # edge-tts, piper-tts, pillow, aggdraw, numpy
```
Voce (`"engine"` nel JSON o `--engine`):
- **kokoro** (consigliato offline): Kokoro-82M, licenza Apache 2.0 (uso commerciale consentito),
  voce italiana `im_nicola` (maschile) o `if_sara` (femminile), 24 kHz. Il modello (~350 MB) si scarica
  una volta in `voices/kokoro/` da GitHub.
- **edge**: edge-tts con it-IT-DiegoNeural (servizio online non ufficiale, richiede `speech.platform.bing.com`).
- **piper**: voce offline "riccardo_fasol" (qualità bassa, solo come ultima risorsa).
- **auto**: edge, se non raggiungibile kokoro, altrimenti piper.

## Uso
```bash
python make_video.py topics/stelle_di_neutroni.json --name short1
# -> output/short1.mp4 e output/short1.txt (titolo, descrizione, 10 tag)
```

### Nuovo video
```bash
python make_video.py --new-topic buchi_neri   # crea topics/buchi_neri.json
# compila testo, titoli, icone e colori delle scene (una frase di ~12 parole = 4-5 s)
python make_video.py topics/buchi_neri.json --name short2
```
Icone disponibili: `star, spoon_star, explosion, sun_squeeze, atom, spin, fall,
collision, ring, bell, bulb, planet, dna` (nomi sconosciuti → icona "?").

`--silent-test` prova il montaggio senza rete (audio muto, tempi stimati).

### Scene animate (es. `topics/buchi_neri.json` → `short2`)
Una scena con `"anim": "nome"` viene disegnata fotogramma per fotogramma da `animations.py`
(disco di accrescimento che ruota, luce che si piega, astronauta che si allunga, galassia che gira…)
invece di essere un'immagine fissa. Animazioni disponibili: `spaghetti, accretion, light_bend,
stretch, clocks, galaxy, first_photo, hawking, zeros`. Le scene senza `anim` usano ancora le icone.
`anim_atoms.py` aggiunge le scene di `topics/atomi_vuoto.json` → `short3` ("Non hai mai toccato niente"):
`touch, atom_cloud, repel, floating, stadium, sugar, star_forge, supernova, stardust`.
Con `"stars": false` in una scena si toglie il cielo stellato di sfondo.

Opzioni globali nel JSON:
| chiave | effetto |
|---|---|
| `"transitions"` | lista di transizioni xfade a rotazione (`circleopen`, `slideup`, `zoomin`, `smoothup`, `radial`, `dissolve`…) |
| `"pause"` | pausa dopo ogni frase in secondi (default 0.30) |
| `"music"` | `"synth"` = tappeto ambient generato dal codice, oppure percorso di un file audio; con ducking sotto la voce |
| `"music_db"` | volume della musica (default -24) |
| `"whoosh"` | `true` = effetto sonoro a ogni transizione |
| `"engine"` / `"kokoro_voice"` | motore voce (`kokoro`, `edge`, `piper`, `auto`) e voce Kokoro (`im_nicola`, `if_sara`) |
| `"rate"` | velocità della voce, es. `"-12%"` = più lenta |
| `"voice_polish"` | `true` = catena di trattamento voce (meno sintetica) |
| `"voice_takes"` / `"target_wps"` | Piper: fino a N prese per frase, tiene quella più vicina al ritmo obiettivo (parole/s, es. 2.9) |
| `"progress_bar"` | `false` = nasconde la barra di avanzamento in basso (default `true`) |
| `"punch"` | `true` = breve zoom "a pugno" all'inizio di ogni scena (tranne la prima) |
| `"fade_in"` / `"fade_out"` | dissolvenza dal/al nero (default disattivate: primo fotogramma pieno, taglio netto) |

## Rifinitura di un video già generato
`edit_v2.py` rimonta un MP4 esistente senza rigenerarlo: taglio del finale, pause
accorciate a ~0,18 s, niente dissolvenza iniziale, movimento leggero, loudnorm -14 LUFS.
```bash
python edit_v2.py output/short1.mp4 output/short1_v2.mp4 /tmp/lavoro            # pause 0,18 s
python edit_v2.py output/short1.mp4 output/short1_v3.mp4 /tmp/lavoro \
    --pause 0.32 --tempo 0.88 --voice-polish                                      # ritmo naturale
```
`--tempo 0.88` rallenta voce e video insieme (tono invariato, sottotitoli sincronizzati);
`--voice-polish` applica una catena di equalizzazione/compressione per una voce meno sintetica.
