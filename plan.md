# Plan: Karaoke App Enhancements - YouTube History, Microphone Support & Professional UI

## User Requirements (Turkish → English)

1. **YouTube Download Optimization**
   - Same video should not be downloaded more than once (duplicate detection)
   - Same video should not be processed/separated twice (reuse cached stems)

2. **YouTube History Feature**
   - View history of previously downloaded YouTube videos
   - Select from history to quickly load previous downloads

3. **Microphone Pass-Through**
   - Route selected microphone audio to output device
   - Sing along with karaoke tracks (vocals + instrumental + microphone mix)

4. **Professional UI Redesign**
   - Current design is "very bad" - needs professional overhaul
   - Modern, polished appearance

---

## USER ANSWERS ✅

### 1. Microphone Features: **D - All of the above**
- ✅ Basic pass-through (microphone → speakers)
- ✅ Voice effects (reverb/echo for professional karaoke sound)
- ✅ Recording (save karaoke performances to WAV file)

### 2. YouTube History UI: **Right-side hover menu**
- **Design**: Slide-out panel from right side (on hover/click)
- **Top section**: Queue (upcoming songs to play)
- **Bottom section**: History (previously downloaded videos)

### 3. Professional UI Style: **C - Dark Gradient (Spotify/Netflix style)**
- Dark backgrounds with smooth gradients
- Vibrant accent colors
- Modern, sleek appearance

### 4. Duplicate Detection: **C - Show notification**
- Brief notification: "Using cached version of [video title]"
- Auto-load cached file without re-downloading

### 5. Additional Requirement: **Video Format Conversion**
If unsupported video codec detected (e.g., AV1):
- Use FFmpeg to convert to H.264 (widely supported codec)
- Command: `ffmpeg -i input.av1.mkv -c:v libx264 -preset veryfast -crf 20 -c:a copy output.mp4`
- Show progress during conversion
- Cache converted file for future use

---

## Current Implementation Analysis

### YouTube Downloads (from exploration)
**File**: `karaoke_app/audio/youtube_downloader.py`
- Downloads to: `karaoke_app/downloads/`
- Naming: Uses YouTube video title + extension
- Format: `bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best`
- **No duplicate detection** - will re-download same video
- **No history tracking** - only implicit in `app_settings.json`

### Stem Caching (from exploration)
**File**: `karaoke_app/audio/separation.py`
- Cache location: `karaoke_app/stems_cache/`
- Deduplication: MD5 hash of file content (lines 50-65)
- Cache structure: `{base_name}_{hash[:8]}/` with vocals + instrumental WAV files
- **Works correctly** - won't re-process identical audio content

### Audio Architecture (from exploration)
**File**: `karaoke_app/audio/playback.py`
- Uses `sounddevice` library with `sd.OutputStream` (output-only)
- Real-time mixing of vocals + instrumental in playback loop
- Block size: 2048 samples, stereo, float32
- **No microphone input** currently implemented
- **Easily extensible**: `sounddevice` supports bidirectional `sd.Stream` for input+output

### Current UI Design (from exploration)
**File**: `karaoke_app/ui/main_window.py`
- **Style**: Dark material design with inline QSS stylesheets
- **Colors**: `#2c3e50` (background), `#3498db` (primary), `#e74c3c` (accent)
- **Layout**: Status bar → Video/Placeholder + Mixer → Transport controls
- **Issues**: Inline styles everywhere, no consistent spacing, basic controls

### Settings Storage (from exploration)
**File**: `karaoke_app/settings/app_settings.json`
- Stores per-song mix settings (volumes, mute states)
- **Can be extended** to store YouTube download history

---

## Proposed Implementation Plan

### FEATURE 1: YouTube Download Deduplication & History

#### 1.1 Download History Database

**File**: Create `karaoke_app/data/download_history.json`

```json
{
  "downloads": [
    {
      "video_id": "dQw4w9WgXcQ",
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "title": "Rick Astley - Never Gonna Give You Up",
      "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
      "downloaded_at": "2025-12-06T02:15:30Z",
      "file_path": "D:/projects/yusuf/kareoke/karaoke_app/downloads/Rick Astley - Never Gonna Give You Up.mp4",
      "duration": 213,
      "file_size_mb": 3.7
    }
  ]
}
```

**Rationale**: YouTube video ID is unique identifier, prevents duplicate downloads

#### 1.2 Modify YouTubeDownloader Class

**File**: `karaoke_app/audio/youtube_downloader.py`

**Changes**:
1. Add `DownloadHistory` class to manage history JSON (lines 15-80)
2. Extract video ID from URL before download (new method `extract_video_id()`)
3. Check history for existing download by video ID
4. If exists: return cached file path, don't re-download
5. If new: download, then save metadata to history
6. Add method `get_history()` to return list of previous downloads

**New Methods**:
```python
def extract_video_id(self, url: str) -> str:
    """Extract YouTube video ID from URL."""
    # Parse URL and extract 'v' parameter or path segment

def check_cached_download(self, video_id: str) -> Optional[Path]:
    """Check if video already downloaded, return path if exists."""

def save_to_history(self, video_id: str, url: str, info: dict, file_path: Path):
    """Save download metadata to history."""
```

#### 1.3 Add Right-Side Slide-Out Menu (Queue + History)

**File**: Create `karaoke_app/ui/components/side_panel.py`

**Design Specifications**:
- **Position**: Right side of main window
- **Behavior**: Slides out on hover or click of edge handle
- **Width**: 350px when open, 20px handle when closed
- **Animation**: Smooth slide (200ms duration)
- **Sections**:
  - **Top 60%**: Queue (upcoming songs)
  - **Bottom 40%**: History (previously downloaded videos)

**Queue Section Features**:
- List of songs ready to play (drag-to-reorder support)
- Add songs via "Add to Queue" button
- Current playing song highlighted
- Remove songs from queue

**History Section Features**:
- Scrollable list of previously downloaded videos
- Each item shows: thumbnail, title, duration, date
- Click to load directly (no re-download)
- Right-click menu: "Load", "Remove from History", "Re-download"
- Show notification when cached version is used

**Implementation**:
```python
class SidePanel(QWidget):
    def __init__(self):
        self.is_open = False
        self.handle = QPushButton("☰")  # hamburger icon
        self.queue_list = QListWidget()
        self.history_list = QListWidget()
        self.animation = QPropertyAnimation(self, b"maximumWidth")

    def toggle_panel(self):
        # Animate slide in/out

    def add_to_queue(self, file_path):
        # Add to queue list

    def load_from_history(self, item):
        # Load cached download, show notification
```

**Integration in main_window.py**:
- Add side panel to right side of main layout
- Connect to YouTube download completion → add to history
- Show notification via QTimer + fade animation when loading cached file

---

### FEATURE 2: Microphone Pass-Through

#### 2.1 Modify StemPlayer for Bidirectional Audio

**File**: `karaoke_app/audio/playback.py`

**Key Changes**:

1. **Replace `sd.OutputStream` with `sd.Stream`** (lines 220-226)
   ```python
   self.stream = sd.Stream(
       samplerate=self.sample_rate,
       channels=2,
       dtype='float32',
       blocksize=chunk_size,
       callback=self._audio_callback  # NEW: callback-based approach
   )
   ```

2. **Add microphone input handling**:
   - New properties: `microphone_enabled`, `microphone_volume`, `microphone_device_id`
   - In `_audio_callback()`: read input data (microphone), mix with stems, return output

3. **Mixing equation update** (line 250):
   ```python
   # OLD: mixed = (vocals * vocals_gain) + (instrumental * instrumental_gain)
   # NEW: mixed = (vocals * vocals_gain) + (instrumental * instrumental_gain) + (microphone * mic_gain)
   ```

4. **Latency handling**: Add configurable latency parameter for echo prevention

**Voice Effects Implementation** (reverb/echo):
- Add `VoiceEffects` class using scipy.signal for reverb/echo processing
- Reverb: Convolutional reverb using impulse response
- Echo: Simple delay line with configurable delay time and feedback
- UI controls: Reverb intensity slider, echo delay slider, echo feedback slider

**Recording Implementation**:
- Add `RecordingManager` class to save mixed output
- Format: WAV file (44.1kHz, stereo, 16-bit)
- Save location: `karaoke_app/recordings/`
- Filename: `Recording_{song_name}_{timestamp}.wav`
- UI controls: "Record" button (toggles on/off), recording indicator (red dot)
- Auto-save on stop or when song ends

#### 2.2 Add Microphone Device Selection UI

**File**: `karaoke_app/ui/main_window.py`

**New UI Components** (in mixer panel, lines 277-386):

**Microphone Section** (third column in mixer):
1. QComboBox for input device selection (populated via `sd.query_devices()`)
2. Microphone volume slider (vertical, matching vocals/instrumental style)
3. Microphone mute checkbox
4. Monitor indicator (shows when microphone is active - green LED)

**Voice Effects Section** (below mixer):
1. Reverb intensity slider (0-100%)
2. Echo delay slider (50-500ms)
3. Echo feedback slider (0-80%)
4. "Effects On/Off" toggle button

**Recording Section** (in transport controls):
1. "● REC" button (red, toggles recording on/off)
2. Recording indicator (animated red dot when recording)
3. Recording time display (MM:SS)
4. "Open Recordings Folder" button

**Settings Integration**:
- Save selected microphone device to `app_settings.json`
- Restore on app startup

#### 2.3 Audio Device Enumeration

**File**: Create `karaoke_app/audio/device_manager.py`

```python
import sounddevice as sd

class AudioDeviceManager:
    @staticmethod
    def get_input_devices() -> list[dict]:
        """Get all available input devices."""
        devices = sd.query_devices()
        return [d for d in devices if d['max_input_channels'] > 0]

    @staticmethod
    def get_output_devices() -> list[dict]:
        """Get all available output devices."""
        devices = sd.query_devices()
        return [d for d in devices if d['max_output_channels'] > 0]
```

---

### FEATURE 3: Professional UI Redesign (Dark Gradient - Spotify/Netflix Style)

#### 3.1 Create External Stylesheet

**File**: Create `karaoke_app/ui/styles/dark_gradient_theme.qss`

**Design System**:
- **Color Palette**:
  - Background Base: `#0a0a0a` → `#1a1a1a` (dark gradient)
  - Surface: `#181818` with subtle gradients
  - Primary Accent: `#1db954` (Spotify green) or `#e50914` (Netflix red)
  - Secondary Accent: `#535353`
  - Text Primary: `#ffffff`
  - Text Secondary: `#b3b3b3`
  - Borders: `rgba(255, 255, 255, 0.1)`

- **Typography**:
  - Font Family: "Segoe UI", "Helvetica Neue", sans-serif
  - Headings: 16-24px, semi-bold
  - Body: 13-14px, regular
  - Labels: 11-12px, medium

**Stylesheet Structure**:
```qss
/* Main Window - Dark gradient background */
QMainWindow {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #0a0a0a,
        stop:0.5 #121212,
        stop:1 #1a1a1a
    );
}

/* Status Bar - Sleek top bar */
#statusLabel {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1a1a1a,
        stop:1 #242424
    );
    color: #ffffff;
    font-size: 13px;
    font-weight: 500;
    padding: 16px 24px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

/* Primary Buttons - Vibrant gradients */
QPushButton#selectSongButton {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1db954,
        stop:1 #1ed760
    );
    border: none;
    border-radius: 24px;
    padding: 16px 32px;
    font-size: 15px;
    font-weight: 600;
    color: #000000;
}

QPushButton#selectSongButton:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1ed760,
        stop:1 #1fdf64
    );
}

QPushButton#youtubeButton {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #e50914,
        stop:1 #f40612
    );
    border: none;
    border-radius: 24px;
    padding: 16px 32px;
    font-size: 15px;
    font-weight: 600;
    color: #ffffff;
}

/* Mixer Panel - Elevated card with gradient */
#mixerPanel {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(40, 40, 40, 0.8),
        stop:1 rgba(24, 24, 24, 0.8)
    );
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 24px;
}

/* Sliders - Modern with gradients */
QSlider::groove:vertical {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    width: 10px;
}

QSlider::handle:vertical {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1db954,
        stop:1 #1ed760
    );
    border: 2px solid #000000;
    border-radius: 12px;
    height: 24px;
    width: 24px;
    margin: 0 -7px;
}

QSlider::handle:vertical:hover {
    height: 28px;
    width: 28px;
    border-radius: 14px;
}

/* Video Widget - Rounded with border */
QVideoWidget {
    background-color: #000000;
    border: 2px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
}

/* Placeholder - Modern centered text */
#placeholderLabel {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #181818,
        stop:1 #242424
    );
    border-radius: 16px;
    color: #b3b3b3;
    font-size: 20px;
    font-weight: 300;
}

/* Transport Controls - Icon buttons */
QPushButton#playButton {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #1db954,
        stop:1 #1ed760
    );
    border: none;
    border-radius: 28px;
    width: 56px;
    height: 56px;
    color: #000000;
    font-size: 24px;
}

QPushButton#pauseButton {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #ffa500,
        stop:1 #ffb732
    );
    border: none;
    border-radius: 28px;
    width: 56px;
    height: 56px;
    color: #000000;
    font-size: 24px;
}

/* Side Panel - Slide-out menu */
#sidePanel {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #0f0f0f,
        stop:1 #1a1a1a
    );
    border-left: 1px solid rgba(255, 255, 255, 0.05);
}

#sidePanelHandle {
    background: rgba(29, 185, 84, 0.2);
    border: none;
    border-radius: 4px 0 0 4px;
    color: #1db954;
    font-size: 18px;
}

#sidePanelHandle:hover {
    background: rgba(29, 185, 84, 0.4);
}
```

#### 3.2 Improve Layout & Spacing

**File**: `karaoke_app/ui/main_window.py`

**Changes**:
1. Add consistent margins (15-20px) between components
2. Increase button sizes for better touch targets
3. Add subtle shadows/borders for depth
4. Improve video widget frame (rounded corners, border)
5. Better alignment of mixer controls

**Specific Updates**:
- Lines 176-240: Improve spacing in `setup_ui()`
- Lines 277-386: Redesign mixer panel with better proportions
- Lines 387-512: Enhance transport controls layout

#### 3.3 Add Visual Polish

**Enhancements**:
1. **Animations**: Add fade-in/fade-out for status messages
2. **Icons**: Use QIcon for buttons instead of emoji (more professional)
3. **Tooltips**: Add helpful tooltips to all controls
4. **Progress Indicators**: Circular progress for separation (instead of dialog)
5. **Waveform Display**: Optional visualization in video placeholder area

**Icon Library** (add to requirements):
```txt
# UI Icons
qtawesome>=1.3.0  # Font Awesome icons for Qt
```

#### 3.4 Responsive Layout

**Changes**:
- Make mixer panel collapsible (hide/show with button)
- Adjust video widget size based on window size
- Minimum window size: 1200x800 (was 1000x700)

---

### FEATURE 4: Video Codec Conversion (AV1 → H.264)

#### 4.1 Detect Unsupported Codecs

**File**: Modify `karaoke_app/audio/separation.py`

**Method**: Add codec detection in `_extract_audio_from_video()`

```python
def _detect_video_codec(self, file_path: Path) -> str:
    """Detect video codec using ffmpeg probe."""
    import subprocess
    import json

    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams',
        str(file_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)

    for stream in data.get('streams', []):
        if stream['codec_type'] == 'video':
            return stream['codec_name']

    return 'unknown'
```

#### 4.2 Convert Unsupported Codecs

**File**: Create `karaoke_app/audio/video_converter.py`

```python
import ffmpeg
from pathlib import Path
from typing import Optional, Callable

class VideoConverter:
    """Converts videos with unsupported codecs to H.264."""

    UNSUPPORTED_CODECS = {'av1', 'vp9', 'hevc'}

    @staticmethod
    def needs_conversion(codec: str) -> bool:
        """Check if codec needs conversion."""
        return codec.lower() in VideoConverter.UNSUPPORTED_CODECS

    def convert_to_h264(
        self,
        input_path: Path,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Path:
        """
        Convert video to H.264 codec.

        Args:
            input_path: Path to input video file
            progress_callback: Optional progress callback

        Returns:
            Path to converted video file
        """
        output_path = input_path.parent / f"{input_path.stem}_h264.mp4"

        logger.info(f"Converting {input_path.name} to H.264...")

        if progress_callback:
            progress_callback(10, "Converting video to H.264...")

        try:
            # Get video duration for progress tracking
            probe = ffmpeg.probe(str(input_path))
            duration = float(probe['format']['duration'])

            # Convert with progress tracking
            process = (
                ffmpeg
                .input(str(input_path))
                .output(
                    str(output_path),
                    vcodec='libx264',     # H.264 codec
                    preset='veryfast',    # Fast encoding
                    crf=20,               # Quality (18-23 is good)
                    acodec='copy',        # Copy audio without re-encoding
                    **{'movflags': 'faststart'}  # Enable streaming
                )
                .overwrite_output()
                .global_args('-progress', 'pipe:1')
                .run_async(pipe_stdout=True, pipe_stderr=True)
            )

            # Track progress
            while True:
                line = process.stdout.readline().decode('utf-8')
                if not line:
                    break

                if 'out_time_ms' in line:
                    time_ms = int(line.split('=')[1])
                    current_time = time_ms / 1000000.0  # Convert to seconds
                    percent = min(int((current_time / duration) * 80) + 10, 90)

                    if progress_callback:
                        progress_callback(percent, f"Converting video... {percent}%")

            process.wait()

            if process.returncode == 0:
                if progress_callback:
                    progress_callback(100, "Conversion complete!")

                logger.info(f"Conversion successful: {output_path}")
                return output_path
            else:
                stderr = process.stderr.read().decode('utf-8')
                raise Exception(f"FFmpeg conversion failed: {stderr}")

        except Exception as e:
            logger.error(f"Video conversion failed: {str(e)}", exc_info=True)
            raise Exception(f"Failed to convert video: {str(e)}")
```

#### 4.3 Integrate with Separation Flow

**File**: Modify `karaoke_app/audio/separation.py`

**Update `_extract_audio_from_video()` method**:

```python
def _extract_audio_from_video(self, file_path: Path) -> Path:
    """
    Extract audio from video files.
    Converts unsupported codecs (AV1, VP9) to H.264 first.
    """
    import ffmpeg
    from .video_converter import VideoConverter

    video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.flv', '.m4v', '.webm'}

    if file_path.suffix.lower() not in video_extensions:
        return file_path

    # Check codec
    codec = self._detect_video_codec(file_path)
    logger.info(f"Detected video codec: {codec}")

    # Convert if unsupported
    if VideoConverter.needs_conversion(codec):
        logger.warning(f"Codec {codec} not supported, converting to H.264...")
        converter = VideoConverter()
        file_path = converter.convert_to_h264(file_path, self.progress_callback)
        logger.info(f"Using converted file: {file_path}")

    # Extract audio (existing code)
    temp_audio_path = file_path.parent / f"{file_path.stem}_temp_audio.wav"

    # ... rest of extraction code ...
```

#### 4.4 UI Integration

**File**: `karaoke_app/ui/main_window.py`

**Add notification for conversion**:
- Show toast notification when video is being converted
- Display conversion progress in progress dialog
- Update status label: "Converting AV1 to H.264..."

---

## Critical Files to Modify

### New Files to Create:

1. **`karaoke_app/data/download_history.json`**
   - YouTube history storage (JSON format)
   - Stores video ID, title, thumbnail, file path, download date

2. **`karaoke_app/audio/device_manager.py`**
   - Audio device enumeration (input/output devices)
   - Uses sounddevice.query_devices()

3. **`karaoke_app/audio/video_converter.py`**
   - Video codec conversion (AV1/VP9 → H.264)
   - FFmpeg wrapper with progress tracking

4. **`karaoke_app/audio/voice_effects.py`**
   - Voice effects processing (reverb/echo)
   - Uses scipy.signal for DSP

5. **`karaoke_app/audio/recording_manager.py`**
   - Recording session manager
   - Saves mixed output to WAV files

6. **`karaoke_app/ui/styles/dark_gradient_theme.qss`**
   - External stylesheet (Spotify/Netflix style)
   - Dark gradients, vibrant accents

7. **`karaoke_app/ui/components/side_panel.py`**
   - Right-side slide-out menu
   - Queue (top 60%) + History (bottom 40%)

8. **`karaoke_app/ui/components/notification_toast.py`**
   - Toast notification widget
   - For duplicate detection and other notifications

9. **`karaoke_app/recordings/`** (directory)
   - Storage for recorded karaoke performances

### Existing Files to Modify:

1. **`karaoke_app/audio/youtube_downloader.py`** (~150 lines to add)
   - Add `DownloadHistory` class (JSON management)
   - Add `extract_video_id()` method
   - Add duplicate detection in `download()`
   - Save metadata to history after download

2. **`karaoke_app/audio/playback.py`** (~200 lines to modify/add)
   - Replace `sd.OutputStream` with `sd.Stream` (bidirectional)
   - Add microphone input properties
   - Add `_audio_callback()` method for real-time mixing
   - Integrate VoiceEffects and RecordingManager
   - Add microphone volume/mute controls

3. **`karaoke_app/audio/separation.py`** (~80 lines to add)
   - Add `_detect_video_codec()` method
   - Modify `_extract_audio_from_video()` to handle codec conversion
   - Integrate VideoConverter for AV1/VP9 files

4. **`karaoke_app/ui/main_window.py`** (~400 lines to modify/add)
   - Load external stylesheet (dark_gradient_theme.qss)
   - Add SidePanel to right side of layout
   - Add microphone controls (device selector, volume, mute, effects)
   - Add recording controls (REC button, timer, indicator)
   - Add notification toast for duplicate detection
   - Update button object names for stylesheet selectors
   - Increase window minimum size to 1280x800

5. **`karaoke_app/audio/__init__.py`** (~3 lines to add)
   - Export DeviceManager, VoiceEffects, RecordingManager, VideoConverter

6. **`requirements.txt` & `requirements-gpu.txt`** (no changes needed)
   - All dependencies already available (sounddevice, scipy, ffmpeg-python, etc.)

---

## Implementation Order

1. **Phase 1: YouTube History** (1-2 hours)
   - Add download history tracking
   - Implement duplicate detection
   - Basic history UI (dropdown or list)

2. **Phase 2: Microphone Support** (2-3 hours)
   - Modify StemPlayer for bidirectional audio
   - Add device enumeration
   - Add microphone UI controls
   - Test with real microphone

3. **Phase 3: UI Redesign** (3-4 hours)
   - Create external stylesheet
   - Apply consistent spacing/margins
   - Add icons and visual polish
   - Test responsiveness

---

## Testing Plan

### YouTube History:
- ✅ Download video A → check history file created
- ✅ Download video A again → should skip, use cached
- ✅ Download video B → history should have 2 entries
- ✅ Select from history → should load without download
- ✅ Restart app → history should persist

### Microphone:
- ✅ Enable microphone → should hear live voice in output
- ✅ Adjust microphone volume → should change gain
- ✅ Mute microphone → should silence input
- ✅ Change input device → should switch microphone source
- ✅ Play with stems → should mix vocals + instrumental + microphone

### UI Design:
- ✅ Window resize → layout should adapt
- ✅ All buttons → hover effects work
- ✅ Dark/light theme toggle (if implemented)
- ✅ High DPI displays → scaling correct

---

## Risk Assessment

### YouTube History:
- **Low risk**: Simple JSON storage, minimal complexity
- **Consideration**: File path validation (moved/deleted files)

### Microphone:
- **Medium risk**: Audio synchronization, potential latency issues
- **Mitigation**: Use small block sizes (512-1024), test latency on user's hardware
- **Consideration**: Echo feedback if output goes to speakers (recommend headphones)

### UI Redesign:
- **Low risk**: Visual changes, no functional impact
- **Consideration**: User preference - may need theme toggle

---

## Dependencies

### Already Available:
- `sounddevice>=0.4.6` - Supports bidirectional streams ✅
- `PySide6>=6.8.0` - Full UI framework ✅
- `yt-dlp>=2024.12.0` - YouTube metadata extraction ✅

### To Add:
- `qtawesome>=1.3.0` - Professional icons (optional, only if using icon library)

---

## Notes

- **Microphone latency**: Target <20ms for comfortable singing experience
- **YouTube rate limiting**: yt-dlp handles this, but consider adding cooldown for rapid downloads
- **History pruning**: Consider auto-delete downloads older than 30 days to save disk space
- **Voice effects**: If requested, use scipy.signal for reverb/echo (already in dependencies)
