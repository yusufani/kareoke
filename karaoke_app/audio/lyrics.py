"""
Lyrics discovery.

The point of this module: given nothing but a messy YouTube title, come back
with time-synced lyrics whenever they exist anywhere, for free, with no API key.

Primary source is LRCLIB (https://lrclib.net) — a public, key-less, community
database that serves LRC-format *synced* lyrics. It is queried several ways
because a raw YouTube title almost never matches a clean database record on the
first try:

    1. exact  artist + track + duration      (highest confidence)
    2. search free-text "artist track"       (what LRCLIB's own site does)
    3. search artist + track                 (ranked)
    4. search the whole cleaned title        (ranked)
    5. the same with artist/track swapped    (titles are written both ways)
    6. search track only                     (ranked)

Anything that comes back is scored on duration proximity and title similarity,
so a wrong-but-plausible hit does not win over a right one. If no synced lyrics
exist we still take plain lyrics — the stage can scroll those — and only when
nothing at all is found does the caller fall back to playing the video.
"""
import json
import logging
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..core.paths import LYRICS_DIR

logger = logging.getLogger(__name__)


LRCLIB_BASE = "https://lrclib.net/api"
USER_AGENT = "Encore Karaoke Studio v2.0 (https://github.com/encore-karaoke)"
TIMEOUT = 8.0

STATE_SYNCED = "synced"
STATE_PLAIN = "plain"
STATE_NONE = "none"


# --------------------------------------------------------------------------
# Title cleaning
# --------------------------------------------------------------------------

# Bracketed junk: "(Official Video)", "[4K Remaster]", "(Lyrics)", ...
_BRACKET_NOISE = re.compile(
    r"[\(\[\{]\s*[^\)\]\}]*\b("
    r"official|video|audio|lyric|lyrics|sözleri|sozleri|karaoke|instrumental|"
    r"remaster(ed)?|hd|hq|4k|8k|full|mv|m/v|visualizer|performance|live|"
    r"cover|version|edit|mix|clip|klip|altyazı|altyazili|with lyrics|letra"
    r")\b[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)
# Bare noise words left outside of brackets.
_BARE_NOISE = re.compile(
    r"\b(official\s+(music\s+)?video|official\s+audio|lyric\s+video|"
    r"karaoke\s+version|karaoke|instrumental|with\s+lyrics|hd|hq|4k|"
    r"resmi\s+video|şarkı\s+sözleri|sarki\s+sozleri)\b",
    re.IGNORECASE,
)
_FEAT = re.compile(r"\s*[\(\[]?\s*(feat\.?|ft\.?|featuring)\s+[^\)\]\|]+[\)\]]?", re.IGNORECASE)
# Trailing decoration people tack onto lyric-video titles.
_TRAILING_NOISE = re.compile(
    r"(\s+(lyrics?|s[öo]zleri|letra|karaoke|instrumental|audio|video)"
    r"(\s+(on\s+(the\s+)?screen|with\s+lyrics|hd|hq|4k))?\s*)+$",
    re.IGNORECASE,
)
_TRAILING_PIPE = re.compile(r"\s*\|.*$")
_MULTISPACE = re.compile(r"\s{2,}")
_SEPARATORS = (" - ", " – ", " — ", " -- ", " ‒ ", " ― ", "-", "–", "—")


def _tidy(text: str) -> str:
    text = _BRACKET_NOISE.sub(" ", text)
    text = _FEAT.sub(" ", text)
    text = _BARE_NOISE.sub(" ", text)
    text = _MULTISPACE.sub(" ", text).strip()
    text = _TRAILING_NOISE.sub("", text)
    text = text.strip(" \t-–—_·•|,")
    return _MULTISPACE.sub(" ", text).strip()


def split_title(raw_title: str, channel: str = "") -> Tuple[str, str]:
    """Guess ``(artist, track)`` from a YouTube title.

    Falls back to the uploading channel as the artist, which is right
    surprisingly often — official artist channels post their own songs.
    """
    title = _TRAILING_PIPE.sub("", raw_title or "").strip()
    title = _tidy(title)

    for sep in _SEPARATORS:
        if sep in title:
            left, _, right = title.partition(sep)
            left, right = _tidy(left), _tidy(right)
            if left and right:
                return left, right

    artist = _tidy(re.sub(r"\s*-\s*Topic$", "", channel or "", flags=re.IGNORECASE))
    return artist, title


def _fold(text: str) -> str:
    """Lowercase, strip accents and punctuation — for fuzzy comparison only."""
    text = (text or "").lower()
    text = text.replace("ı", "i").replace("ğ", "g").replace("ş", "s")
    text = text.replace("ö", "o").replace("ü", "u").replace("ç", "c")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return _MULTISPACE.sub(" ", text).strip()


def _similar(a: str, b: str) -> float:
    fa, fb = _fold(a), _fold(b)
    if not fa or not fb:
        return 0.0
    if fa in fb or fb in fa:
        return 0.95
    return SequenceMatcher(None, fa, fb).ratio()


# --------------------------------------------------------------------------
# LRC parsing
# --------------------------------------------------------------------------

_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> List[Tuple[float, str]]:
    """Parse LRC text into ``[(seconds, line)]``, sorted, blanks preserved.

    A single LRC line can carry several timestamps (repeated choruses), so each
    tag produces its own entry.
    """
    lines: List[Tuple[float, str]] = []
    for raw in (text or "").splitlines():
        stamps = list(_LRC_TIME.finditer(raw))
        if not stamps:
            continue
        content = raw[stamps[-1].end():].strip()
        for match in stamps:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            frac = match.group(3) or "0"
            # Two-digit fractions are centiseconds, three are milliseconds.
            divisor = 100.0 if len(frac) <= 2 else 1000.0
            stamp = minutes * 60 + seconds + int(frac) / divisor
            lines.append((stamp, content))
    lines.sort(key=lambda item: item[0])
    return lines


def split_plain(text: str) -> List[str]:
    """Plain lyrics into non-empty display lines."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


# --------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------


@dataclass
class LyricsResult:
    state: str = STATE_NONE
    source: str = ""
    artist: str = ""
    track: str = ""
    # Synced: [(seconds, text)]. Plain: [(-1.0, text)].
    lines: List[Tuple[float, str]] = field(default_factory=list)
    offset: float = 0.0

    @property
    def synced(self) -> bool:
        return self.state == STATE_SYNCED and len(self.lines) > 1

    @property
    def found(self) -> bool:
        return self.state in (STATE_SYNCED, STATE_PLAIN) and bool(self.lines)

    def to_dict(self) -> Dict:
        return {
            "state": self.state,
            "source": self.source,
            "artist": self.artist,
            "track": self.track,
            "offset": self.offset,
            "lines": [[t, s] for t, s in self.lines],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "LyricsResult":
        return cls(
            state=data.get("state", STATE_NONE),
            source=data.get("source", ""),
            artist=data.get("artist", ""),
            track=data.get("track", ""),
            offset=float(data.get("offset", 0.0)),
            lines=[(float(t), str(s)) for t, s in data.get("lines", [])],
        )


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _get_json(url: str, params: Optional[Dict] = None):
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        url = f"{url}?{urllib.parse.urlencode(clean)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            logger.debug("lyrics HTTP %s for %s", exc.code, url)
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.debug("lyrics request failed for %s: %s", url, exc)
        return None


# --------------------------------------------------------------------------
# Candidate scoring
# --------------------------------------------------------------------------


def _score(record: Dict, artist: str, track: str, duration: float) -> float:
    """Rank an LRCLIB record against what we were looking for.

    The name part is scored three ways and the best one wins, because a YouTube
    title gives no reliable clue which half is the artist. A title written
    "<song> - <artist> Lyrics" parses artist-first and comes out backwards;
    scoring the swapped orientation as well rescues it, and comparing the two
    full strings rescues the cases where neither split is clean.
    """
    record_track = record.get("trackName", "")
    record_artist = record.get("artistName", "")

    straight = 2.4 * _similar(track, record_track)
    if artist:
        straight += 1.3 * _similar(artist, record_artist)
    swapped = 2.4 * _similar(artist, record_track) + 1.3 * _similar(track, record_artist)
    combined = 3.2 * _similar(f"{artist} {track}", f"{record_artist} {record_track}")
    score = max(straight, swapped, combined)

    if duration and record.get("duration"):
        delta = abs(float(record["duration"]) - duration)
        if delta <= 2:
            score += 2.0
        elif delta <= 5:
            score += 1.2
        elif delta <= 12:
            score += 0.4
        elif delta > 60:
            # A soft nudge, not a veto: uploads carry intros, outros and long
            # fades, so a minute of difference is common and not disqualifying.
            score -= 0.8

    if record.get("syncedLyrics"):
        score += 1.6
    elif record.get("plainLyrics"):
        score += 0.3
    else:
        score -= 3.0

    if record.get("instrumental"):
        score -= 2.5
    return score


def agrees(track: str, artist: str, record_track: str, record_artist: str) -> bool:
    """True when a matched record names the same song we asked for.

    Used before adopting a record's labels for display. Either orientation
    counts: when our parse put the artist first by mistake, the record still
    describes the same song and is in fact the *better* naming of the two, so
    a backwards "<song> / <artist> Lyrics" comes out the right way round. Only
    a record that matches neither way round is rejected.
    """
    straight = (_similar(track, record_track) > 0.6
                and (not artist or _similar(artist, record_artist) > 0.5))
    swapped = (_similar(artist, record_track) > 0.6
               and _similar(track, record_artist) > 0.5)
    return straight or swapped


def _to_result(record: Dict, source: str) -> Optional[LyricsResult]:
    synced = record.get("syncedLyrics")
    plain = record.get("plainLyrics")
    artist = record.get("artistName", "")
    track = record.get("trackName", "")

    if synced:
        lines = parse_lrc(synced)
        if len(lines) > 1:
            return LyricsResult(STATE_SYNCED, source, artist, track, lines)
    if plain:
        lines = [(-1.0, text) for text in split_plain(plain)]
        if lines:
            return LyricsResult(STATE_PLAIN, source, artist, track, lines)
    return None


def _best(records: Sequence[Dict], artist: str, track: str, duration: float,
          source: str, threshold: float = 1.9) -> Optional[LyricsResult]:
    best_record, best_score = None, threshold
    for record in records or ():
        if not isinstance(record, dict):
            continue
        value = _score(record, artist, track, duration)
        if value > best_score:
            best_record, best_score = record, value
    if best_record is None:
        return None
    logger.info(
        "lyrics match via %s: %s — %s (score %.2f)",
        source, best_record.get("artistName"), best_record.get("trackName"), best_score,
    )
    return _to_result(best_record, source)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def _cache_path(song_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", song_id)[:80]
    return LYRICS_DIR / f"{safe}.json"


def load_cached(song_id: str) -> Optional[LyricsResult]:
    path = _cache_path(song_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return LyricsResult.from_dict(json.load(handle))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def save_cached(song_id: str, result: LyricsResult) -> Path:
    path = _cache_path(song_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Could not cache lyrics: %s", exc)
    return path


def load_sidecar(media_path: Path) -> Optional[LyricsResult]:
    """Pick up a hand-placed ``song.lrc`` sitting next to the media file."""
    for suffix in (".lrc", ".txt"):
        candidate = Path(media_path).with_suffix(suffix)
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = parse_lrc(text)
        if len(lines) > 1:
            return LyricsResult(STATE_SYNCED, "local file", lines=lines)
        plain = [(-1.0, item) for item in split_plain(text)]
        if plain:
            return LyricsResult(STATE_PLAIN, "local file", lines=plain)
    return None


def fetch(
    raw_title: str,
    channel: str = "",
    duration: float = 0.0,
    artist_hint: str = "",
    track_hint: str = "",
    budget: float = 20.0,
) -> LyricsResult:
    """Search every free source for the lyrics of one song.

    ``budget`` caps the wall-clock time spent looking. A song nobody has
    transcribed would otherwise walk the whole query plan while the singer
    waits, and the video fallback is a perfectly good answer. It is generous
    because the lookup never blocks playback — but it is finite, because a
    prepare job should not hang on one unlucky title.

    Runs on a worker thread — it makes several blocking HTTP calls and must
    never be invoked from the GUI thread.
    """
    # Hints get the same cleaning as a raw title. A caller passing the library's
    # stored title is handing us whatever YouTube called it, decoration included.
    artist = _tidy(artist_hint or "")
    track = _tidy(track_hint or "")
    if not track:
        artist, track = split_title(raw_title, channel)
    if not track:
        track = _tidy(raw_title)

    queries = _build_queries(artist, track, raw_title, channel)
    logger.info("Looking up lyrics for artist=%r track=%r (%.0fs)", artist, track, duration)

    # Synced lyrics win outright. Plain ones are remembered but do not stop the
    # search — a later query may still turn up a timed version of the same song.
    plain_fallback: Optional[LyricsResult] = None
    for result in _run_lrclib(queries, artist, track, duration, budget):
        if result is None:
            continue
        if result.synced:
            return result
        if result.found and plain_fallback is None:
            plain_fallback = result

    if plain_fallback:
        return plain_fallback
    ovh = _lyrics_ovh(artist, track)
    if ovh:
        return ovh
    logger.info("No lyrics found for %r", raw_title)
    return LyricsResult(STATE_NONE)


def _build_queries(artist: str, track: str, raw_title: str, channel: str) -> List[Dict]:
    """The ordered plan of LRCLIB calls, most specific first."""
    plan: List[Dict] = []

    def add(kind: str, **params):
        if params.get("track_name") or params.get("q"):
            plan.append({"kind": kind, **params})

    # Ordered by observed yield, because the search runs against a time budget
    # and the queries that most often work should get their turn first. The
    # free-text search comes second: it is what LRCLIB's own site uses, and it
    # tolerates the artist and track being run together or the wrong way round.
    add("get", track_name=track, artist_name=artist)
    add("search", q=f"{artist} {track}".strip())
    add("search", track_name=track, artist_name=artist)
    cleaned = _tidy(raw_title)
    if _fold(cleaned) not in {_fold(track), _fold(f"{artist} {track}")}:
        add("search", q=cleaned)
    if artist:
        # Titles are written both ways round; try the mirror image.
        add("get", track_name=artist, artist_name=track)
        add("search", track_name=artist, artist_name=track)
    add("search", q=track)
    if channel:
        add("search", track_name=track, artist_name=_tidy(channel))

    # De-duplicate while preserving order.
    seen, unique = set(), []
    for item in plan:
        key = tuple(sorted(item.items()))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _run_lrclib(queries: Sequence[Dict], artist: str, track: str, duration: float,
                budget: float = 20.0):
    """Yield a result per query attempt (None when that attempt found nothing)."""
    deadline = time.monotonic() + max(budget, 2.0)
    for original in queries:
        if time.monotonic() > deadline:
            logger.info("lyrics search hit its %.0fs budget; giving up", budget)
            return
        query = dict(original)
        kind = query.pop("kind")
        try:
            if kind == "get":
                params = dict(query)
                if duration:
                    params["duration"] = int(round(duration))
                record = _get_json(f"{LRCLIB_BASE}/get", params)
                if record is None and duration:
                    record = _get_json(f"{LRCLIB_BASE}/get", query)
                if isinstance(record, dict):
                    scored = _score(record, artist, track, duration)
                    if scored > 1.5:
                        result = _to_result(record, "LRCLIB")
                        if result:
                            logger.info("lyrics exact hit: %s — %s", record.get("artistName"),
                                        record.get("trackName"))
                            yield result
                            continue
            else:
                records = _get_json(f"{LRCLIB_BASE}/search", query)
                if isinstance(records, list) and records:
                    result = _best(records, artist, track, duration, "LRCLIB")
                    if result:
                        yield result
                        continue
        except Exception as exc:  # network flakiness must never kill the job
            logger.debug("lyrics query %s failed: %s", query, exc)
        yield None
        # Be polite to a free community service.
        time.sleep(0.05)


def _lyrics_ovh(artist: str, track: str) -> Optional[LyricsResult]:
    """Plain-text fallback. No timings, but better than nothing."""
    if not artist or not track:
        return None
    url = "https://api.lyrics.ovh/v1/{}/{}".format(
        urllib.parse.quote(artist, safe=""), urllib.parse.quote(track, safe="")
    )
    data = _get_json(url)
    if not isinstance(data, dict):
        return None
    text = (data.get("lyrics") or "").strip()
    if len(text) < 40:
        return None
    lines = [(-1.0, item) for item in split_plain(text) if not item.startswith("Paroles de")]
    if not lines:
        return None
    logger.info("lyrics match via lyrics.ovh: %s — %s", artist, track)
    return LyricsResult(STATE_PLAIN, "lyrics.ovh", artist, track, lines)
