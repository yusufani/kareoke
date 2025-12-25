# Karaoke Separation Studio

A professional Windows desktop karaoke application with AI-powered vocal separation. Transform any song into a customizable karaoke experience with independent control over vocals and instrumental tracks.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **AI-Powered Stem Separation**: Automatically separates any audio/video file into vocals and instrumental using state-of-the-art Demucs v4
- **Real-Time Mixing**: Independent volume faders for vocals and instrumental with instant feedback
- **Video Playback**: Full video support with synchronized audio stems
- **Smart Caching**: Stems are cached locally - separation happens only once per song
- **GPU Acceleration**: Optional NVIDIA GPU support for 5-10x faster separation
- **Professional UI**: Clean, intuitive interface built with Qt (PySide6)
- **Per-Song Settings**: Remembers your mix preferences for each song
- **Solo/Mute Controls**: Quickly isolate vocals or instrumental
- **Transport Controls**: Play, pause, stop, and seek with precision

## System Requirements

### Minimum Requirements
- **OS**: Windows 10 64-bit or Windows 11
- **RAM**: 8 GB (16 GB recommended)
- **Storage**: 2 GB for application + 100-200 MB per song for stems
- **CPU**: Intel Core i5 or AMD Ryzen 5 (or equivalent)

### Optional for GPU Acceleration
- **GPU**: NVIDIA GPU with CUDA support (GTX 1060 or better)
- **VRAM**: 4 GB minimum (6+ GB recommended)

### Audio Formats Supported
- **Audio**: MP3, WAV, FLAC
- **Video**: MP4, MKV, AVI

## Installation

### 🚀 Quick Start (Recommended - UV)

**NEW!** We now support [UV](https://github.com/astral-sh/uv) - the ultra-fast Python package manager (10-100x faster than pip)!

```cmd
setup-uv.bat
```

This will:
- Auto-install UV if not present
- Create virtual environment
- Install all dependencies in ~45 seconds (vs 8 minutes with pip)

See [UV_GUIDE.md](UV_GUIDE.md) for detailed UV documentation.

### Option 1: Run from Source (Developers)

1. **Clone or download this repository**
   ```cmd
   cd d:\projects\yusuf\kareoke
   ```

2. **Run the setup script**

   **With UV (10-100x faster):**
   ```cmd
   setup-uv.bat
   ```

   **Traditional pip:**
   ```cmd
   setup.bat
   ```

   This will:
   - Create a Python virtual environment
   - Ask if you want GPU support
   - Install all dependencies

3. **Run the application**
   ```cmd
   run.bat
   ```

   or with UV:
   ```cmd
   run-uv.bat
   ```

### Option 2: Use Pre-built Executable (End Users)

1. **Download the latest release**
   - Download `KaraokeSeparationStudio-v1.0.0.zip` from the releases page

2. **Extract and run**
   - Extract the ZIP file to any location
   - Navigate to `KaraokeSeparationStudio` folder
   - Double-click `KaraokeSeparationStudio.exe`

## Building from Source

To create a standalone executable:

```cmd
build.bat
```

The executable will be created in `dist\KaraokeSeparationStudio\`

## Usage Guide

### First-Time Setup

1. **Launch the application**
   - Double-click `run.bat` or the `.exe` file

2. **Select a song**
   - Click the "SELECT SONG" button
   - Choose an MP3, MP4, or other supported file

3. **Wait for AI separation**
   - First time: 1-5 minutes depending on your CPU/GPU
   - Subsequent times: Instant (stems are cached)

### Using the Karaoke Controls

#### Mixer Panel (Right Side)

- **Vocals Slider**: Control vocal volume (0-100%)
- **Instrumental Slider**: Control backing track volume (0-100%)
- **Mute Buttons**: Quickly mute either stem
- **Solo Buttons**: Isolate one stem (mutes the other)
- **Reset Mix**: Return both sliders to 100%

#### Transport Controls (Bottom)

- **Play**: Start playback from current position
- **Pause**: Pause playback (keeps position)
- **Stop**: Stop and return to beginning
- **Seek Slider**: Jump to any position in the song

### Common Use Cases

#### Classic Karaoke (Sing Along)
1. Set **Vocals** to **0%**
2. Set **Instrumental** to **100%**
3. Press **Play** and sing!

#### Practice with Original Vocals
1. Set **Vocals** to **30-50%**
2. Set **Instrumental** to **100%**
3. Sing along with subtle vocal guidance

#### Instrumental Analysis
1. Click **Instrumental Solo**
2. Study the backing track

#### Vocal Study
1. Click **Vocals Solo**
2. Analyze the vocal technique

## Project Structure

```
kareoke/
├── karaoke_app/
│   ├── main.py                  # Application entry point
│   ├── utils.py                 # Logging and utilities
│   ├── ui/
│   │   ├── __init__.py
│   │   └── main_window.py       # Main UI window
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── separation.py        # Demucs integration
│   │   └── playback.py          # Real-time stem mixing
│   ├── resources/               # Icons and resources
│   ├── stems_cache/             # Cached separated stems
│   ├── logs/                    # Application logs
│   └── settings/                # User settings
├── requirements.txt             # CPU-only dependencies
├── requirements-gpu.txt         # GPU-enabled dependencies
├── karaoke_app.spec            # PyInstaller spec
├── setup.bat                    # Setup script
├── run.bat                      # Run script
├── build.bat                    # Build script
└── README.md                    # This file
```

## Technical Details

### AI Separation Engine

- **Model**: Demucs v4 (Hybrid Transformer)
- **Architecture**: 4-source separation (drums, bass, other, vocals)
- **Output**: 2 stems - vocals and instrumental (drums + bass + other)
- **Quality**: 16-bit, 44.1/48 kHz stereo WAV

### Audio Playback

- **Engine**: PyAudio with custom real-time mixer
- **Latency**: ~50ms (ultra-responsive volume changes)
- **Synchronization**: Frame-accurate stem alignment
- **Buffer Size**: 2048 samples (adjustable for lower latency)

### Caching System

- **Location**: `karaoke_app/stems_cache/`
- **Key**: MD5 hash of original file (first 8 chars)
- **Structure**: Separate folder per song with vocals and instrumental WAV files
- **Invalidation**: Manual only (Tools → Re-generate Stems)

### Video Playback

- **Framework**: Qt Multimedia (QMediaPlayer)
- **Synchronization**: Video synced to audio stems (not vice versa)
- **Drift Correction**: Automatic resync if drift > 100ms
- **Audio**: Muted (stems used instead for mixing control)

## Performance Tips

### Separation Speed

| Hardware | Typical 3-Minute Song |
|----------|----------------------|
| CPU Only (i5) | 3-5 minutes |
| CPU Only (i7/Ryzen 7) | 2-3 minutes |
| GPU (GTX 1660) | 30-60 seconds |
| GPU (RTX 3060+) | 15-30 seconds |

### Optimization

- **First run per song is slow** - separation is compute-intensive
- **Subsequent runs are instant** - stems are cached
- **Use GPU version** if you have NVIDIA GPU
- **Close other apps** during separation for faster processing
- **SSD recommended** for faster stem loading

## Troubleshooting

### Application won't start
- Ensure Python 3.10 or 3.11 is installed
- Run `setup.bat` again
- Check `logs/` folder for error messages

### Separation is very slow
- Normal on CPU-only systems (3-5 min per song)
- Install GPU version if you have NVIDIA GPU
- Close other applications to free up RAM/CPU

### Audio crackling or glitches
- Increase buffer size in `audio/playback.py` (line 94)
- Close other audio applications
- Update audio drivers

### Video not playing
- Ensure file is a supported video format (MP4, MKV, AVI)
- Try re-encoding with standard codecs
- Check Qt Multimedia codec support

### "CUDA out of memory" error
- Your GPU doesn't have enough VRAM
- Use CPU version instead: reinstall with `requirements.txt`

### Stems sound wrong
- Click Tools → Re-generate Stems
- Try a different audio file (some files may have issues)
- Report issues with specific files

## Known Limitations

1. **Separation quality varies by song**
   - Modern pop/rock: Excellent
   - Classical/orchestral: Good
   - Heavy metal/electronic: Variable

2. **First-run separation is slow**
   - CPU: 2-5 minutes per song
   - GPU: 15-60 seconds per song

3. **Large disk space usage**
   - Each song requires ~100-200 MB for stems
   - Clear cache manually if needed

4. **No real-time effects**
   - No reverb, echo, or pitch shifting
   - Focus is on high-quality separation and mixing

## FAQ

**Q: Can I use this commercially?**
A: Check the license. For personal use, yes. For commercial use, consult licensing.

**Q: Does this work offline?**
A: Yes! All processing is 100% local. No internet required after installation.

**Q: Can I export the separated stems?**
A: Yes! Stems are saved as WAV files in `stems_cache/` - copy them anywhere.

**Q: What's the difference between CPU and GPU versions?**
A: GPU version is 5-10x faster for separation. Everything else is identical.

**Q: Can I use this on Mac or Linux?**
A: Currently Windows only. Mac/Linux ports are possible but not yet implemented.

**Q: How accurate is the vocal separation?**
A: Demucs v4 is state-of-the-art (as of 2024). Quality is very high for most modern music.

## Dependencies

### Core Libraries
- **PySide6** 6.6+ - Qt for Python (GUI framework)
- **PyTorch** 2.1+ - Deep learning framework
- **Demucs** 4.0+ - AI separation model
- **soundfile** 0.12+ - Audio I/O
- **sounddevice** 0.4+ - Real-time audio playback
- **NumPy** 1.24+ - Numerical computing

### Optional
- **CUDA Toolkit** 11.8 (for GPU version)

## License

MIT License - See LICENSE file for details.

## Credits

- **Demucs**: Developed by Facebook Research / Meta AI
- **PySide6**: Qt for Python
- **PyTorch**: Facebook AI Research

## Support

For issues, questions, or feature requests, please:
1. Check the logs in `logs/` folder
2. Review the troubleshooting section above
3. Open an issue on GitHub (if applicable)

## Version History

### v1.0.0 (2024)
- Initial release
- Demucs v4 integration
- Real-time stem mixing
- Video playback support
- Smart caching system
- GPU acceleration support

---

**Built with ❤️ for karaoke enthusiasts and vocal learners**
