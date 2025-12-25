# Quick Start Guide

Get up and running with Karaoke Separation Studio in 5 minutes!

## For End Users (Pre-built Executable)

### 1. Download & Extract
- Download `KaraokeSeparationStudio-v1.0.0.zip`
- Extract to any folder
- No installation required!

### 2. Launch
- Double-click `KaraokeSeparationStudio.exe`
- Wait a few seconds for the app to start

### 3. Load Your First Song
- Click **"📁 SELECT SONG"**
- Choose an MP3 or MP4 file
- Wait 1-5 minutes for AI separation (first time only)

### 4. Start Singing!

**Classic Karaoke Mode**:
1. Drag **Vocals** slider all the way down (0%)
2. Keep **Instrumental** at 100%
3. Press **▶ Play**
4. Sing along! 🎤

**Practice Mode** (with faint vocals):
1. Set **Vocals** to 20-30%
2. Keep **Instrumental** at 100%
3. Press **▶ Play**
4. Learn the melody!

## For Developers (Run from Source)

### 1. Install Python
```cmd
# Download Python 3.11 from python.org
python --version  # Verify it's installed
```

### 2. Setup
```cmd
cd d:\projects\yusuf\kareoke
setup.bat
```
Choose **GPU** if you have NVIDIA graphics, otherwise choose **CPU**.

### 3. Run
```cmd
run.bat
```

### 4. Use the App
Same as above - click SELECT SONG and start karaoke!

## Tips for Best Experience

### For Better Separation Quality
- Use high-quality source files (320kbps MP3 or lossless)
- Modern pop/rock songs work best
- Avoid heavily compressed or low-quality files

### For Faster Performance
- **GPU version**: 10x faster separation (if you have NVIDIA GPU)
- **SSD**: Faster stem loading
- **Close other apps**: More RAM for processing

### Common Settings

| Use Case | Vocals | Instrumental |
|----------|--------|--------------|
| Pure Karaoke | 0% | 100% |
| Learning | 30% | 100% |
| Duet Practice | 50% | 100% |
| Instrumental Study | 0% (muted) | 100% (solo) |
| Vocal Study | 100% (solo) | 0% (muted) |

## Keyboard Shortcuts

(Note: Currently not implemented - use mouse/buttons)

## Troubleshooting

### App won't start
- Right-click → Properties → Unblock (if downloaded)
- Run as Administrator (if needed)
- Check Windows Defender didn't quarantine it

### Separation takes forever
- Normal for CPU-only: 3-5 minutes per song
- Use GPU version for faster processing
- Subsequent loads are instant (cached)

### No sound
- Check Windows volume mixer
- Ensure correct audio device is selected
- Try restarting the app

### Video not showing
- Only MP4, MKV, AVI are supported
- Audio-only files show a placeholder (normal)

## Next Steps

- **Read full manual**: See [README.md](README.md)
- **Customize settings**: Experiment with sliders
- **Share your experience**: Rate and review!

---

**That's it! Enjoy your karaoke experience!** 🎵🎤
