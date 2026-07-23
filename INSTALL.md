# Installation

Encore runs from source on macOS, Linux and Windows. There is no installer yet —
see [PACKAGING.md](PACKAGING.md) for where that stands.

Türkçe özet en altta ↓

---

## What you need

| | |
|---|---|
| **Python** | 3.10 – 3.13 (the setup script installs 3.11 for you) |
| **ffmpeg** | on your PATH — required, see below |
| **Disk** | ~4 GB for dependencies, plus ~50 MB per prepared song |
| **RAM** | 8 GB works; 16 GB is comfortable |
| **GPU** | optional. NVIDIA (CUDA) or Apple Silicon (Metal) make separation several times faster; CPU works everywhere |

### ffmpeg is not optional

YouTube hands over audio in containers libsndfile cannot read (m4a/AAC, webm/Opus),
and ffmpeg is what turns them into something the separator can open. Without it,
every download fails at the decode step.

```bash
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian / Ubuntu
winget install Gyan.FFmpeg   # Windows
```

Check it:

```bash
ffmpeg -version
```

---

## Install

### macOS / Linux

```bash
git clone https://github.com/yusufani/kareoke.git
cd kareoke
./setup.sh
```

`setup.sh` installs [uv](UV_GUIDE.md) if it is missing, creates `.venv` with
Python 3.11, and installs everything from `requirements.txt`. It takes a minute
or two on a normal connection.

Then:

```bash
./run.sh
```

### Windows

```cmd
git clone https://github.com/yusufani/kareoke.git
cd kareoke
setup.bat
run.bat
```

### Without uv

If you would rather use plain `pip`:

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m karaoke_app.main
```

---

## GPU

Encore picks the fastest device it can find on its own — CUDA, then Apple Metal,
then CPU — and says which in the log:

```
Apple Silicon GPU detected, using Metal (MPS)
Separation engine initialized. Device: mps
```

Nothing needs configuring on Apple Silicon; Metal support ships with the default
`torch` wheel.

**NVIDIA:** the default wheel is CPU-only on Linux and Windows. For CUDA:

```bash
uv pip install -r requirements-gpu.txt
```

To force a particular device — useful when a GPU driver misbehaves:

```bash
KARAOKE_DEVICE=cpu ./run.sh          # or cuda, or mps
```

Separation also falls back to CPU by itself if a GPU kernel fails mid-run.

---

## First run

1. The window opens and the drawer is already showing, because the library is
   empty.
2. In the background, the demucs model (~80 MB) downloads once from Hugging Face
   and stays cached in `~/.cache/torch/`. You need to be online for this.
3. Type a song name, press Enter, hit **Download** on a result.
4. Watch the badge go *Finding lyrics* → *Downloading* → *Separating stems* →
   **✓ synced lyrics**, then press **▶ Play**.

Everything Encore writes lives under `karaoke_app/` — `downloads/`,
`stems_cache/`, `lyrics_cache/`, `recordings/`, `data/`, `logs/`. Point
`ENCORE_HOME` somewhere else to move all of it:

```bash
ENCORE_HOME=~/Music/Encore ./run.sh
```

---

## Checking it works

The log for each run is written to `karaoke_app/logs/`. A healthy start looks
like this:

```
Encore starting from /path/to/karaoke_app
UI font: Space Grotesk · mono font: JetBrains Mono
Library loaded: 16 songs
Output open: 48000 Hz, block 256, latency 22.0 ms
Apple Silicon GPU detected, using Metal (MPS)
Mic 1 open on device 5
```

The mixer header shows the same latency figure live, and each mic channel has an
input meter under its fader — if it moves when you speak, capture is working.

---

## Troubleshooting

**No sound at all.** Check the *Vocals* and *Music* faders in the mixer — a
previous session's positions are restored, and both at zero is silent by design.
Then check **⚙ → Audio settings → Output device**.

**"Could not open output device".** Another application may hold the device
exclusively. Pick a different output in the settings; Encore falls back to the
system default automatically if the chosen one fails.

**A microphone will not open.** The strip shows the reason in the status bar.
On macOS, the first attempt triggers the microphone permission prompt — if you
dismissed it, re-enable Encore (or your terminal) under System Settings →
Privacy & Security → Microphone.

**The microphone echoes.** Effects are off by default, so this is almost always
the room: you are listening on speakers and the speaker is feeding the mic.
Headphones fix it. See the *If the microphone echoes* section of the
[README](README.md).

**Crackling or dropouts.** The log counts them at the end of playback. Raise the
buffer by setting `block_size` in `karaoke_app/data/config.json` to 512, and
restart. Larger buffer, more monitoring latency, fewer dropouts.

**Separation fails with "returned silence".** The track is too long for the
available memory. Encore refuses anything over 20 minutes up front; this message
means a shorter track still exhausted the GPU. Try `KARAOKE_DEVICE=cpu`.

**Download fails with "format is not available".** Update yt-dlp — YouTube
changes formats often:

```bash
uv pip install --upgrade yt-dlp
```

**Lyrics are not found for a song that definitely has them.** The title probably
did not parse. Try a search result with a cleaner title — `Artist - Song` beats
`SONG ✨ artist ✨ (lyrics) (4k)`. The lookup retries automatically the next time
you play the song.

---

## Updating

```bash
git pull
uv pip install -r requirements.txt --upgrade
```

Your library, stems, downloads and settings are untouched by an update — none of
them are tracked by git.

## Uninstalling

Delete the folder. Everything, including the virtual environment and every
cached stem, lives inside it. The only thing outside is the demucs model cache
in `~/.cache/torch/`.

---

## Türkçe

**Gereken:** Python 3.10–3.13 (kurulum betiği 3.11'i kendisi kuruyor) ve
**ffmpeg**. ffmpeg zorunlu: YouTube'dan gelen sesi çözebilmek için gerekiyor.

```bash
brew install ffmpeg      # macOS
./setup.sh               # bir kez
./run.sh                 # her seferinde
```

Windows'ta `setup.bat`, sonra `run.bat`.

**Ekran kartı** kendiliğinden bulunuyor — Apple Silicon'da Metal, NVIDIA'da CUDA
(`requirements-gpu.txt` ile), yoksa CPU. Zorlamak için `KARAOKE_DEVICE=cpu`.

**İlk çalıştırmada** ayrıştırma modeli (~80 MB) arka planda bir kez iniyor, yani
internet gerekiyor. Sonrası çevrimdışı çalışır.

**Uygulamanın yazdığı her şey** `karaoke_app/` altında. Başka yere almak için
`ENCORE_HOME=~/Muzik/Encore ./run.sh`.

**Ses yoksa** önce mikserdeki *Vocals* ve *Music* fader'larına bak — bir önceki
oturumun konumları geri yükleniyor. **Mikrofon yankı yapıyorsa** neredeyse her
zaman sebep odadır: hoparlörden dinlerken ses mikrofona geri giriyor, kulaklık
çözer.
