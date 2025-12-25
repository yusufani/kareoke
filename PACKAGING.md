# Packaging Guide for Developers

This guide explains how to create a distributable Windows executable for Karaoke Separation Studio.

## Prerequisites

1. **Completed installation** from source (see INSTALL.md)
2. **All dependencies installed** in virtual environment
3. **PyInstaller installed** (included in requirements.txt)

## Quick Build

### Option 1: Use Build Script (Recommended)

```cmd
build.bat
```

This will:
1. Clean previous builds
2. Run PyInstaller with the spec file
3. Create executable in `dist\KaraokeSeparationStudio\`

### Option 2: Manual PyInstaller Command

```cmd
.venv\Scripts\activate
pyinstaller karaoke_app.spec
```

## Build Output

After successful build:

```
dist/
└── KaraokeSeparationStudio/
    ├── KaraokeSeparationStudio.exe    # Main executable
    ├── _internal/                      # Dependencies and libraries
    │   ├── PySide6/
    │   ├── torch/
    │   ├── demucs/
    │   └── ... (other libraries)
    └── resources/                      # Application resources
```

**Total size**: ~800 MB - 1.5 GB depending on GPU/CPU version

## PyInstaller Spec File Explained

The `karaoke_app.spec` file controls the build process:

### Key Sections

#### 1. Data Files
```python
datas = [
    (str(app_dir / 'resources'), 'resources'),
]
```
- Includes application resources (icons, etc.)
- Add more data files here if needed

#### 2. Hidden Imports
```python
hiddenimports = [
    'PySide6.QtCore',
    'torch',
    'demucs',
    # ... etc
]
```
- PyInstaller can't auto-detect these imports
- Add any missing modules here if you get import errors

#### 3. Exclusions
```python
excludes=[
    'matplotlib',
    'PIL',
    'tkinter',
]
```
- Reduces package size by excluding unused libraries
- Carefully test after adding exclusions

#### 4. EXE Configuration
```python
exe = EXE(
    ...
    console=False,  # No console window
    icon=None,      # Add your .ico file here
)
```

## Customization

### Adding an Icon

1. Create or obtain a `.ico` file (256x256 recommended)
2. Save as `karaoke_app/resources/icon.ico`
3. Edit `karaoke_app.spec`:
   ```python
   icon='karaoke_app/resources/icon.ico'
   ```
4. Rebuild

### Reducing Package Size

Current size: ~1 GB (GPU) or ~500 MB (CPU)

**Strategies to reduce**:

1. **Use CPU-only version**:
   - Saves ~500 MB (no CUDA libraries)
   - Edit requirements to exclude GPU packages

2. **Exclude unused PyTorch components**:
   ```python
   excludes=['torch.distributions', 'torch.nn.quantized']
   ```

3. **Use UPX compression**:
   - Already enabled: `upx=True`
   - Downloads UPX automatically

4. **Exclude development tools**:
   - Already done: excluded matplotlib, PIL, tkinter

### Creating a Single-File Executable

**Warning**: Single-file EXE is slower to start (~10-20 seconds)

Edit `karaoke_app.spec`:
```python
exe = EXE(
    ...
    exclude_binaries=False,  # Change to False
    ...
)

# Comment out COLLECT section
# coll = COLLECT(...)
```

Then rebuild.

## Distribution

### Creating a Release Package

1. **Build the application**:
   ```cmd
   build.bat
   ```

2. **Test the executable**:
   - Run `dist\KaraokeSeparationStudio\KaraokeSeparationStudio.exe`
   - Test all features (file loading, separation, playback, video)
   - Check different file formats

3. **Create README for users**:
   - Copy `INSTALL.md` (executable section) to `dist\KaraokeSeparationStudio\README.txt`
   - Add any last-minute notes

4. **Create ZIP archive**:
   ```cmd
   cd dist
   powershell Compress-Archive -Path KaraokeSeparationStudio -DestinationPath KaraokeSeparationStudio-v1.0.0.zip
   ```

5. **Upload to release platform**:
   - GitHub Releases
   - Your own server
   - Include release notes

### Release Checklist

- [ ] Version number updated in `karaoke_app/__init__.py`
- [ ] Version number updated in `main.py`
- [ ] Changelog updated
- [ ] All features tested in built executable
- [ ] Tested on clean Windows machine (no Python installed)
- [ ] README included in package
- [ ] LICENSE included
- [ ] Virus scan completed (VirusTotal)

## Testing the Build

### Test on Development Machine

```cmd
cd dist\KaraokeSeparationStudio
KaraokeSeparationStudio.exe
```

### Test on Clean Machine

**Important**: Test on a PC without Python/development tools!

1. Copy `dist\KaraokeSeparationStudio\` to USB drive
2. Run on another Windows PC
3. Verify:
   - Application launches
   - File selection works
   - Separation completes
   - Playback works
   - Video playback works (if applicable)
   - Settings persist

## Troubleshooting Build Issues

### Import errors in built executable

**Symptom**: App works in dev, fails in EXE with import errors

**Solution**:
1. Check logs (exe creates logs in same folder)
2. Add missing imports to `hiddenimports` in spec file
3. Rebuild

### Missing DLLs

**Symptom**: "DLL not found" errors

**Solution**:
1. Identify missing DLL (from error message)
2. Add to `binaries` in spec file:
   ```python
   binaries = [
       ('path/to/missing.dll', '.'),
   ]
   ```
3. Rebuild

### Executable too large

**Symptom**: 2+ GB executable

**Solution**:
- Use CPU-only version (removes CUDA ~500 MB)
- Add more exclusions
- Check for duplicate libraries in `_internal`

### Slow startup (single-file EXE)

**Symptom**: 10-30 second startup time

**Solution**:
- Use folder distribution instead (change back to `exclude_binaries=True`)
- Single-file extracts to temp on every run

### PyTorch/CUDA not working in EXE

**Symptom**: GPU detection fails in built EXE

**Solution**:
1. Ensure CUDA DLLs are included
2. Check `torch` is in `hiddenimports`
3. Test with environment variable:
   ```cmd
   set CUDA_VISIBLE_DEVICES=0
   KaraokeSeparationStudio.exe
   ```

## Advanced: Code Signing (Optional)

To avoid Windows SmartScreen warnings:

1. **Obtain code signing certificate**
   - Purchase from certificate authority
   - Or use self-signed (limited benefit)

2. **Sign the executable**:
   ```cmd
   signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com dist\KaraokeSeparationStudio\KaraokeSeparationStudio.exe
   ```

3. **Verify signature**:
   - Right-click EXE → Properties → Digital Signatures

## Build Environment Best Practices

1. **Use clean virtual environment**:
   - Delete `.venv` and recreate before building releases
   - Ensures no dev dependencies leak in

2. **Pin dependency versions**:
   - Use exact versions in `requirements.txt`
   - Prevents breaking changes

3. **Test on multiple Windows versions**:
   - Windows 10 (minimum version)
   - Windows 11

4. **Document build process**:
   - Update this file with any changes
   - Keep changelog updated

## Continuous Integration (Optional)

For automated builds, consider:

- **GitHub Actions**: Automate builds on every release
- **Example workflow**: Build on tag push
- **Artifacts**: Upload built EXE as release asset

Example `.github/workflows/build.yml`:
```yaml
name: Build Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pyinstaller karaoke_app.spec
      - uses: actions/upload-artifact@v2
        with:
          name: KaraokeSeparationStudio
          path: dist/KaraokeSeparationStudio/
```

## Questions?

For build-related issues:
1. Check PyInstaller documentation
2. Review logs in `build/` folder
3. Open issue on GitHub

---

**Happy packaging!** 📦
