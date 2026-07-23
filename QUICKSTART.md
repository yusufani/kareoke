# Quick start

## 1. Install

```bash
./setup.sh
```

macOS/Linux. On Windows run `setup.bat` instead.

You also need ffmpeg on your PATH:

```bash
brew install ffmpeg
```

(Debian/Ubuntu: `sudo apt install ffmpeg`.)

## 2. Run

```bash
./run.sh
```

## 3. Sing

1. **Add songs** → type a song name → Enter.
2. **↓ Download** on the result you want.
3. Watch the badge: *Finding lyrics* → *Downloading* → *Separating stems* → **✓ synced lyrics**.
4. **▶ Play**. The lyric lights up word by word as it is sung.

The first song takes longer than the rest — the separation model loads once, in
the background, while you are still searching.

## While a song is playing

- **Click a mic channel's name** (*Mic 1 ▾*) in the mixer to choose its device.
  The green name and the meter under the fader tell you it is hearing you.
  **⚙ → Audio settings** sets how many microphones you want (up to 4).
- Pull the **Vocals** fader down to sing it yourself; push it up to learn the tune.
- **FX** on a mic channel — reverb, echo, autotune, bass, treble.
- **KEY −/+** moves the song into your range without speeding it up.
- **1.00x −/+** slows it down without dropping the key.
- **A** then **B** loops the section between them.
- **Record** captures your take (the music ducks 6 dB automatically); **Takes**
  lists them and exports to WAV.

You can open **Add songs** at any point and queue the next one. Downloading and
separating happen in the background — the music does not stop.

## If a song has no lyrics anywhere

Encore downloads the video instead and plays it, muted, behind your own separated
audio. You still get the mixer, the mics and every effect. The badge in the corner
of the stage tells you which mode you are in.

## Where things are kept

Everything is under `karaoke_app/` — `downloads/`, `stems_cache/`, `recordings/`,
`lyrics_cache/`. Delete a folder to reclaim the space; anything missing is simply
prepared again next time.
