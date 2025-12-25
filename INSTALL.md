# Installation Guide

This guide will walk you through installing Karaoke Separation Studio on Windows.

## Prerequisites

Before installing, ensure you have:

1. **Windows 10 64-bit or Windows 11**
2. **At least 2 GB of free disk space**
3. **8 GB RAM minimum (16 GB recommended)**

## Method 1: Quick Install (Recommended for End Users)

### Step 1: Download Pre-built Executable

1. Go to the Releases page
2. Download `KaraokeSeparationStudio-v1.0.0.zip`
3. Extract the ZIP file to a location of your choice (e.g., `C:\Program Files\KaraokeSeparationStudio\`)

### Step 2: Run the Application

1. Open the extracted folder
2. Double-click `KaraokeSeparationStudio.exe`
3. Done! The app will launch.

**Note**: Windows may show a SmartScreen warning on first run. Click "More info" → "Run anyway" if you trust the source.

## Method 2: Install from Source (For Developers)

### Step 1: Install Python

1. Download Python 3.11 from [python.org](https://www.python.org/downloads/)
2. **Important**: Check "Add Python to PATH" during installation
3. Verify installation:
   ```cmd
   python --version
   ```
   Should show: `Python 3.11.x`

### Step 2: Download the Source Code

Option A - Clone with Git:
```cmd
git clone https://github.com/yourusername/karaoke-separation-studio.git
cd karaoke-separation-studio
```

Option B - Download ZIP:
1. Download the source code ZIP
2. Extract to a folder (e.g., `D:\projects\karaoke\`)
3. Open Command Prompt in that folder

### Step 3: Run Setup Script

```cmd
setup.bat
```

This will:
1. Create a Python virtual environment
2. Ask if you want GPU support
3. Install all dependencies (takes 5-10 minutes)

**Choose GPU or CPU**:
- **GPU**: If you have NVIDIA graphics card (GTX 1060 or better)
  - Pros: 5-10x faster separation
  - Cons: Larger download (~2 GB)

- **CPU**: For all other systems
  - Pros: Works on any PC
  - Cons: Slower separation (3-5 min per song)

### Step 4: Run the Application

```cmd
run.bat
```

The application window will open!

## Verifying Installation

### Test the Application

1. Launch the app
2. Click "SELECT SONG"
3. Choose any MP3 or MP4 file
4. Wait for separation (first time only)
5. Use the sliders to control vocals/instrumental
6. Press Play

If everything works, you're all set!

### Checking GPU Support (Optional)

If you installed the GPU version, check if it's working:

1. Run the app
2. Open the log file: `karaoke_app\logs\karaoke_app_XXXXXXXX_XXXXXX.log`
3. Look for: `GPU detected: NVIDIA GeForce XXX`

If you see "No GPU detected, using CPU" but you have an NVIDIA GPU:
- Install/update NVIDIA drivers
- Reinstall with `requirements-gpu.txt`

## Troubleshooting Installation

### Python not found
**Error**: `'python' is not recognized as an internal or external command`

**Solution**:
1. Reinstall Python
2. Make sure to check "Add Python to PATH"
3. Restart Command Prompt

### pip install fails
**Error**: Various errors during `pip install`

**Solution**:
1. Update pip:
   ```cmd
   python -m pip install --upgrade pip
   ```
2. Retry `setup.bat`
3. If still fails, try installing dependencies one at a time:
   ```cmd
   pip install PySide6
   pip install torch torchaudio
   pip install demucs
   pip install soundfile sounddevice
   ```

### CUDA/GPU errors
**Error**: `CUDA not found` or `cuDNN not found`

**Solution**:
1. Install the CPU version instead:
   ```cmd
   pip install -r requirements.txt
   ```
2. Or install CUDA Toolkit 11.8 from NVIDIA

### Virtual environment activation fails
**Error**: Cannot activate `.venv`

**Solution**:
1. Delete `.venv` folder
2. Recreate:
   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   ```

## Updating the Application

### For Executable Users
1. Download the new version ZIP
2. Extract to replace old files
3. Your cached stems and settings are preserved (in separate folder)

### For Source Users
1. Pull latest changes:
   ```cmd
   git pull
   ```
2. Update dependencies:
   ```cmd
   .venv\Scripts\activate
   pip install -r requirements.txt --upgrade
   ```

## Uninstalling

### Executable Version
1. Delete the application folder
2. Optionally delete cached stems (if you want to free up space)

### Source Version
1. Delete the project folder
2. That's it! (Virtual environment is self-contained)

## Getting Help

If you encounter issues:

1. **Check logs**: `karaoke_app\logs\` folder
2. **Review README**: See troubleshooting section
3. **Check system requirements**: Ensure your PC meets minimum specs
4. **Report issue**: Open a GitHub issue with log files attached

## Next Steps

Once installed:
- Read [README.md](README.md) for usage guide
- Try the demo songs included
- Customize your karaoke experience!

---

**Enjoy your karaoke sessions!** 🎤🎵
