#!/usr/bin/env python3
"""
Render the README screenshots.

Everything on screen here is invented — the songs, the artists, the lyrics and
the artwork. Nothing touches the network and nothing reads the real library, so
the images carry no copyrighted material: no real song titles, no real lyrics,
no YouTube thumbnails.

    PYTHONPATH=. .venv/bin/python tools/screenshots.py docs
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Run against a throwaway home, so the shots always show shipped defaults and
# the script can never read — or overwrite — the settings and library of
# whoever happens to be using the app on this machine.
os.environ["ENCORE_HOME"] = tempfile.mkdtemp(prefix="encore-shots-")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from karaoke_app.audio.lyrics import STATE_SYNCED, LyricsResult
from karaoke_app.audio.youtube import SearchResult
from karaoke_app.core.library import (LYRICS_NONE, LYRICS_PLAIN, LYRICS_SYNCED,
                                      SongEntry)
from karaoke_app.core.paths import ensure_dirs
from karaoke_app.ui import theme

# -- invented catalogue -----------------------------------------------------
DEMO_SONGS = [
    ("Paper Lanterns", "Halcyon Vale", 214, LYRICS_SYNCED),
    ("Harbour Lights", "The Quiet Ferry", 238, LYRICS_SYNCED),
    ("Salt and Static", "Marlowe June", 252, LYRICS_SYNCED),
    ("Winter Bicycle", "Odd Numbers", 201, LYRICS_PLAIN),
    ("Roman Candle", "Pelican Youth", 187, LYRICS_SYNCED),
    ("Low Tide Radio", "Saltwater Choir", 266, LYRICS_NONE),
]

# Written for this screenshot; not the words of any real song.
DEMO_LYRICS = [
    (0.0, "We left the harbour lights behind"),
    (4.4, "and let the engine hum us home"),
    (9.0, "Every window on the hill is gold"),
    (13.6, "and none of them are ours tonight"),
    (18.2, "So drive a little slower now"),
]

DEMO_RESULTS = [
    ("aaaaaaaaaaa", "Halcyon Vale – Paper Lanterns (Official Video)",
     "Halcyon Vale", 214, 2_100_000),
    ("bbbbbbbbbbb", "The Quiet Ferry – Harbour Lights (Lyric Video)",
     "The Quiet Ferry", 238, 8_400_000),
    ("ccccccccccc", "Marlowe June – Salt and Static (Karaoke / Instrumental)",
     "SingAlong+", 252, 940_000),
    ("ddddddddddd", "Odd Numbers – Winter Bicycle (Lyrics)",
     "LyricWave", 201, 512_000),
]


def build_library():
    entries = []
    for index, (title, artist, duration, state) in enumerate(DEMO_SONGS):
        entries.append(SongEntry(
            id=f"demo{index}", title=title, artist=artist, duration=duration,
            vocals_path="demo", instrumental_path="demo", lyrics_state=state))
    return entries


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "docs")
    out_dir.mkdir(parents=True, exist_ok=True)

    ensure_dirs()
    app = QApplication([])
    theme.resolve_fonts()
    app.setFont(theme.ui_font(13))

    from karaoke_app.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1440, 880)
    window.show()

    def shoot():
        window._frame_timer.stop()
        window.close_drawer()
        library = build_library()
        song = library[0]
        lyrics = LyricsResult(STATE_SYNCED, "LRCLIB", song.artist, song.title,
                              list(DEMO_LYRICS))

        window.current = song
        window._duration = song.duration
        window.now_title.setText(song.title)
        window.now_artist.setText(song.display_artist)
        window._set_source_badge(song)
        window.stage.set_song(song, lyrics, song.duration)
        window.mixer.set_queue(library[1:4])
        window.mixer.set_status("48.0 kHz · 22.0 ms")
        window._open_fx(0)
        for strip in window.mixer.mic_strips:
            strip.set_device("Studio Condenser" if strip.index == 0 else None,
                             strip.index == 0)
            strip.set_level(0.42 if strip.index == 0 else 0.0)

        # Mid-word, so the highlight is visible in the still.
        window.stage._index = -1
        window.stage.tick(DEMO_LYRICS[2][0] + 1.1, True, 1.0)
        window.transport.set_time(64, song.duration)
        window.transport.set_playing(True)
        window.transport.set_marks(40, 96, song.duration)
        window.transport.set_takes(1)
        window.stage.rec_pill.setVisible(True)
        window.stage.rec_pill.set_state(47, True)
        window.stage.rec_pill.raise_()
        window._active_jobs["demo"] = {
            "video_id": "", "title": "Marlowe June – Salt and Static",
            "stage": "separate", "fraction": 0.58,
            "label": "Separating stems 58%"}
        window._update_toast()
        window.resizeEvent(None)
        app.processEvents()
        window.grab().save(str(out_dir / "screenshot-stage.png"))

        window.drawer.set_library(library)
        window.open_drawer("library")
        app.processEvents()
        window.grab().save(str(out_dir / "screenshot-library.png"))

        window.open_drawer("search")
        window.drawer.field.setText("halcyon vale paper lanterns")
        results = [SearchResult(video_id=v, title=t, channel=c, duration=d,
                                views=n, thumbnail="")
                   for v, t, c, d, n in DEMO_RESULTS]
        window.drawer.set_results(results, {e.id: e for e in library})
        window.drawer.cards["aaaaaaaaaaa"].set_ready(library[0])
        window.drawer.cards["bbbbbbbbbbb"].set_busy("download", 0.44,
                                                    "Downloading 44%")
        window.drawer.cards["ccccccccccc"].set_busy("separate", 0.71,
                                                    "Separating stems 71%")
        app.processEvents()
        window.grab().save(str(out_dir / "screenshot-search.png"))

        print(f"wrote three screenshots to {out_dir}/")
        app.quit()

    QTimer.singleShot(1200, shoot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
