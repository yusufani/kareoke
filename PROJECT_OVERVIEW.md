# Karaoke Separation Studio - Project Overview

## Architecture Summary

A professional Windows desktop karaoke application built with Python, featuring AI-powered vocal separation and real-time audio mixing.

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **GUI Framework** | PySide6 (Qt 6) | Main window, controls, video display |
| **AI Separation** | Demucs v4 (PyTorch) | Vocal/instrumental separation |
| **Audio Playback** | sounddevice + numpy | Real-time stem mixing |
| **Video Playback** | QtMultimedia | Video synchronization |
| **Audio I/O** | soundfile, torchaudio | Loading/saving audio files |
| **Packaging** | PyInstaller | Standalone executable creation |

## Project Structure

```
kareoke/
│
├── karaoke_app/                    # Main application package
│   ├── main.py                     # Application entry point
│   ├── utils.py                    # Logging and utilities
│   │
│   ├── ui/                         # User interface components
│   │   ├── __init__.py
│   │   └── main_window.py          # Main window (GUI logic)
│   │
│   ├── audio/                      # Audio processing modules
│   │   ├── __init__.py
│   │   ├── separation.py           # Demucs AI separation
│   │   └── playback.py             # Real-time stem mixer
│   │
│   ├── resources/                  # Icons, assets
│   │   └── icons/
│   │
│   ├── stems_cache/                # Cached separated stems
│   ├── logs/                       # Application logs
│   └── settings/                   # User preferences
│
├── requirements.txt                # CPU-only dependencies
├── requirements-gpu.txt            # GPU-enabled dependencies
├── karaoke_app.spec               # PyInstaller build spec
│
├── setup.bat                       # Initial setup script
├── run.bat                         # Run from source
├── build.bat                       # Build executable
│
├── README.md                       # Main documentation
├── QUICKSTART.md                   # Quick start guide
├── INSTALL.md                      # Installation guide
├── PACKAGING.md                    # Developer packaging guide
├── LICENSE                         # MIT License
└── .gitignore                      # Git ignore patterns
```

## Module Descriptions

### 1. `main.py` - Application Entry Point
- Initializes Qt application
- Sets up high DPI scaling
- Creates application directories
- Configures logging
- Launches main window

**Key Functions**:
- `setup_app_directories()`: Creates required folders
- `main()`: Application entry point

### 2. `utils.py` - Utilities and Logging
- Configures logging to console and file
- Timestamped log files in `logs/` directory
- Separate log levels for console (INFO) and file (DEBUG)

**Key Functions**:
- `setup_logging(app_dir, log_level)`: Initialize logging system

### 3. `audio/separation.py` - AI Stem Separation
- Manages Demucs v4 model
- Handles GPU/CPU device detection
- Implements smart caching with MD5 hashing
- Progress reporting via callbacks
- Generates vocals and instrumental stems

**Key Classes**:
- `SeparationEngine`: Main separation controller

**Key Methods**:
- `separate(file_path, progress_callback)`: Separate audio into stems
- `check_stems_exist(file_path)`: Check cache
- `delete_stems(file_path)`: Remove cached stems

### 4. `audio/playback.py` - Real-Time Stem Mixer
- Synchronized playback of two WAV files
- Independent volume control per stem
- Real-time mixing using numpy
- Mute/solo functionality
- Seek, play, pause, stop controls
- Position callbacks for UI updates

**Key Classes**:
- `StemPlayer`: Audio playback engine

**Key Methods**:
- `load_stems(vocals_path, instrumental_path)`: Load audio files
- `play()`, `pause()`, `stop()`, `seek(position)`: Transport controls
- `set_vocals_volume(volume)`: Real-time volume adjustment
- `set_instrumental_volume(volume)`: Real-time volume adjustment

### 5. `ui/main_window.py` - Main User Interface
- Qt-based GUI with PySide6
- Video playback widget
- Volume faders (vertical sliders)
- Transport controls (play, pause, stop, seek)
- Menu bar (File, Tools, Help)
- Progress dialog for separation
- Settings persistence (JSON)
- Background threading for separation

**Key Classes**:
- `MainWindow`: Main application window
- `SeparationWorker`: Background thread for AI separation

**Key Features**:
- Responsive UI (non-blocking separation)
- Real-time video sync
- Per-song settings memory
- Solo/mute/reset controls

## Data Flow

### File Loading Flow
```
User Selects File
    ↓
Check Cache (separation.py)
    ↓
├─ Cached → Load Stems → Ready to Play
│
└─ Not Cached → Separate (Demucs)
                    ↓
                Save to Cache
                    ↓
                Load Stems → Ready to Play
```

### Playback Flow
```
User Clicks Play
    ↓
Load Vocals WAV ──┐
Load Instrumental WAV ──┤
    ↓
Real-Time Mixer (playback.py)
    │
    ├─ Apply Vocals Volume
    ├─ Apply Instrumental Volume
    ├─ Sum Stems
    ├─ Clip Prevention
    │
    ↓
Output to Sound Device
    ↓
Sync Video Position (if video)
```

### Volume Control Flow
```
User Moves Slider
    ↓
UI Signal → Slot
    ↓
Update StemPlayer Volume
    ↓
Next Audio Callback
    ↓
Apply New Gain
    ↓
Output Updated Mix
```

## Key Design Decisions

### 1. Why Two Playback Systems?
- **QMediaPlayer**: For video (Qt's native player)
- **sounddevice**: For audio stems (real-time mixing control)
- **Reason**: QMediaPlayer can't mix separate audio files in real-time

### 2. Why Demucs over Spleeter?
- Better separation quality (2024 state-of-the-art)
- More active development
- Hybrid Transformer architecture
- Better vocal isolation

### 3. Why Caching with MD5?
- Separation is slow (1-5 minutes)
- Stems are reusable across sessions
- MD5 ensures correct file identification
- Disk space trade-off is worth it

### 4. Why PyInstaller?
- Single-folder distribution
- No Python installation required
- Includes all dependencies
- Native Windows executable

### 5. Why sounddevice over PyAudio?
- Better cross-platform support
- More actively maintained
- Simpler API
- Better NumPy integration

## Performance Characteristics

### Separation Performance
| Hardware | 3-Minute Song |
|----------|---------------|
| CPU i5 | 3-5 minutes |
| CPU i7/Ryzen 7 | 2-3 minutes |
| GPU GTX 1660 | 30-60 seconds |
| GPU RTX 3060+ | 15-30 seconds |

### Memory Usage
- **Idle**: ~200 MB
- **During Separation**: 2-4 GB (CPU) or 2-8 GB (GPU)
- **During Playback**: ~500 MB

### Disk Usage
- **Application**: ~800 MB - 1.5 GB
- **Per Song Cache**: ~100-200 MB (two WAV files)

## Threading Model

### Main Thread (Qt Event Loop)
- UI rendering
- Event handling
- User interaction

### Separation Thread (QThread)
- Demucs model execution
- Audio processing
- Progress updates (via signals)

### Playback Thread (Python thread)
- Audio output streaming
- Real-time mixing
- Position updates

## Error Handling Strategy

1. **Graceful Degradation**: Never crash, always show error dialog
2. **Logging**: All errors logged with stack traces
3. **User Feedback**: Clear, actionable error messages
4. **Recovery**: Allow retry without restart

## Future Enhancement Opportunities

### Short-Term
- [ ] Add keyboard shortcuts
- [ ] Implement pitch shifting
- [ ] Add reverb/echo effects
- [ ] Playlist support
- [ ] Lyrics display (with .lrc files)

### Medium-Term
- [ ] Real-time voice recording and mixing
- [ ] Export mixed audio to file
- [ ] Custom separation models
- [ ] Batch processing

### Long-Term
- [ ] Mac and Linux support
- [ ] Cloud backup of stems
- [ ] Mobile companion app
- [ ] AI-generated harmonies

## Dependencies

### Critical Dependencies
```
PySide6           # GUI framework
torch             # PyTorch (deep learning)
torchaudio        # Audio I/O for PyTorch
demucs            # AI separation model
soundfile         # Audio file I/O
sounddevice       # Real-time audio
numpy             # Numerical computing
```

### Development Dependencies
```
pyinstaller       # Packaging
```

## Build Artifacts

### Development
- `.venv/`: Virtual environment (~2 GB)
- `karaoke_app/logs/`: Log files
- `karaoke_app/stems_cache/`: Cached stems

### Build
- `build/`: PyInstaller temp files (~500 MB)
- `dist/KaraokeSeparationStudio/`: Final executable (~1 GB)

## Testing Strategy

### Manual Testing Checklist
- [ ] File selection (MP3, WAV, MP4)
- [ ] First-time separation (CPU/GPU)
- [ ] Cached stem loading
- [ ] Playback controls
- [ ] Volume faders
- [ ] Mute/solo buttons
- [ ] Seek slider
- [ ] Video sync
- [ ] Settings persistence
- [ ] Re-generate stems

### Performance Testing
- [ ] Separation speed (various files)
- [ ] Memory usage monitoring
- [ ] Audio latency measurement
- [ ] Video sync accuracy

## Known Issues and Limitations

1. **Separation quality varies**: Depends on source material
2. **High memory usage**: PyTorch models are large
3. **No real-time effects**: Focus on quality separation
4. **Windows only**: Qt is cross-platform, but not tested on Mac/Linux
5. **Large package size**: Includes full PyTorch + Demucs

## Maintenance Notes

### Regular Maintenance
- Update dependencies (quarterly)
- Test with new PyTorch versions
- Monitor Demucs updates
- Review user feedback

### Breaking Changes to Watch
- PySide6 API changes
- PyTorch model compatibility
- Demucs architecture updates
- Python version EOL

## Contributing Guidelines

1. **Code Style**: Follow PEP 8
2. **Documentation**: Update docstrings
3. **Testing**: Manual test all features
4. **Logging**: Use appropriate log levels
5. **Error Handling**: Always catch exceptions

## License

MIT License - See LICENSE file for full text.

Third-party components retain their original licenses.

---

**Last Updated**: 2024
**Version**: 1.0.0
**Maintainer**: Karaoke Pro Team
