# Packaging

Building a self-contained Encore with PyInstaller. Everything here has been run;
the notes describe what actually happened, including the parts that are
inconvenient.

---

## Build

```bash
./setup.sh                                   # if you have not already
.venv/bin/python -m PyInstaller --noconfirm --clean encore.spec
```

Windows:

```cmd
setup.bat
.venv\Scripts\python -m PyInstaller --noconfirm --clean encore.spec
```

Takes about a minute on an M-series Mac. You get:

```
dist/
├── Encore/           637 MB   portable folder — ship this on Windows and Linux
│   ├── Encore                 the executable
│   └── _internal/             everything else
└── Encore.app/       644 MB   macOS bundle
```

Run it:

```bash
./dist/Encore/Encore                  # or open dist/Encore.app
```

---

## Why there is an `encore.py`

`karaoke_app/main.py` uses relative imports, so it only works as part of its
package — `python -m karaoke_app.main` is fine. PyInstaller runs the entry
script as `__main__` with no package context, and a build pointed straight at
`karaoke_app/main.py` dies immediately:

```
ImportError: attempted relative import with no known parent package
```

`encore.py` exists to be that entry point: it puts the project root on the path,
imports `karaoke_app.main` the normal way, and calls it. The spec points at
`encore.py`, not at `karaoke_app/main.py`.

---

## What the spec has to say explicitly

**The typefaces.** Space Grotesk and JetBrains Mono are read from
`karaoke_app/ui/fonts/` at start-up rather than imported, so PyInstaller cannot
see them. They are listed under `datas`. Without that the build runs but falls
back to system fonts and looks wrong. Verify after a build:

```bash
find dist -path "*ui/fonts*" -name "*.ttf"
```

**demucs.** It reaches for submodules dynamically, so `collect_submodules`
and `collect_data_files` are both needed. Without them the app starts, the GUI
works, and separation fails the first time you try it — a failure you will only
notice by testing an actual download.

**Microphone permission on macOS.** The bundle declares
`NSMicrophoneUsageDescription`. macOS silently denies capture without it, and
the app just looks like it cannot hear you.

---

## What is *not* in the bundle

**ffmpeg.** It stays an external dependency. It is a large binary with its own
licensing considerations, and bundling it is a decision about redistribution,
not a technical convenience. The app expects `ffmpeg` on PATH; without it every
download fails at the decode step. If you ship Encore to people who will not
install it themselves, you have to make that call and add it to `binaries` in
the spec.

**The separation model.** demucs fetches `htdemucs` (~80 MB) from Hugging Face
the first time it separates anything, and caches it in `~/.cache/torch/`. So a
freshly installed copy needs network once, even though everything else works
offline. To ship it inside the bundle, add the cached files under `datas` and
point `TORCH_HOME` at them from a runtime hook.

---

## Start-up time

The first launch of a frozen build is slow — around **38 seconds** in testing,
while the operating system faults in 640 MB of freshly written files. Every
launch after that is about **1 second** to the window and **4 seconds** to the
separation model being ready.

This surprises people, so it is worth saying in your release notes. There is no
fix short of a smaller bundle.

---

## Size

640 MB, and torch is nearly all of it. Real reductions, in order of how much
they buy you:

- **CPU-only torch on Linux/Windows.** The CUDA wheel carries hundreds of
  megabytes of kernels. Build from `requirements.txt`, not
  `requirements-gpu.txt`, unless you are shipping a GPU build on purpose.
- **`--exclude-module` for what torch drags in.** The spec already drops
  matplotlib, tkinter, PyQt and IPython.
- **UPX** is off. It shaves some size but slows start-up further and trips
  antivirus heuristics on Windows. Not worth it here.

Do not try to trim PySide6 by hand. QtMultimedia is needed for the video
fallback stage and its dependency graph is not obvious.

---

## Signing and distribution

The build is **unsigned**. As shipped:

- **macOS** — Gatekeeper refuses to open it. Users have to right-click → Open,
  or you sign and notarise with an Apple Developer ID.
- **Windows** — SmartScreen shows "unrecognised app" until the binary builds
  reputation, or you sign it with a code-signing certificate.

Neither is a build problem; both need a paid certificate.

---

## Licensing, if you distribute this

Worth reading before you hand a build to anyone:

- **Encore** is MIT.
- **Bundled fonts** — Space Grotesk and JetBrains Mono, both SIL Open Font
  Licence. The licence texts ship alongside them in `karaoke_app/ui/fonts/` and
  must stay there.
- **PySide6** is LGPL. Dynamic linking, as PyInstaller does it, is compatible,
  but the LGPL obliges you to let users replace the Qt libraries.
- **demucs** is MIT; its pretrained weights have their own terms.
- **ffmpeg**, if you choose to bundle it, is LGPL or GPL depending on the build
  you take. A GPL build makes the whole distribution GPL.
- **The music** is not yours. Encore downloads copyrighted recordings and
  fetches lyrics from a community database. Shipping the app is fine; shipping
  it with songs, stems or lyrics inside is not.

---

## Reproducing a clean build

```bash
rm -rf build dist
.venv/bin/python -m PyInstaller --noconfirm --clean encore.spec
ENCORE_HOME=/tmp/encore-test ./dist/Encore/Encore
```

`ENCORE_HOME` sends the test run's library, settings and logs somewhere
disposable, so you are testing a fresh install rather than your own data.

Check the log it writes to `/tmp/encore-test/logs/`. A good build reaches:

```
UI font: Space Grotesk · mono font: JetBrains Mono
Output open: 48000 Hz, block 256, latency 22.0 ms
Separation engine initialized. Device: mps
AI model ready!
```

If the font line names something else, the `datas` entry is broken. If
`AI model ready!` never appears, demucs did not survive the freeze.
