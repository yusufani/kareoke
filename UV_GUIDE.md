# uv — the package manager Encore uses

[English below](#english) · Türkçe önce

`setup.sh` and `setup.bat` use [uv](https://github.com/astral-sh/uv) instead of
pip. You do not have to know anything about it to run Encore — this page is for
when you want to do something the setup script does not cover.

---

## 🇹🇷 Türkçe

### Neden uv?

Encore'un bağımlılıkları ağır: torch, demucs ve PySide6 birlikte birkaç yüz
megabayt. pip bunları çözerken uzun sürüyor, uv aynı işi çok daha hızlı yapıyor
ve indirdiklerini makine genelinde bir önbellekte tutuyor — yani ikinci bir
projede aynı paketler tekrar inmiyor.

| | pip | uv |
|---|---|---|
| Bu projenin kurulumu | birkaç dakika | ~1 dakika |
| Bağımlılık çözümü | yavaş | hızlı |
| Önbellek | proje başına | makine genelinde ortak |
| Python sürümü kurma | yok | var (`uv python install`) |

### Kurulum

`./setup.sh` uv yoksa kendisi kuruyor. Elle kurmak istersen:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh    # macOS / Linux
```

```powershell
irm https://astral.sh/uv/install.ps1 | iex          # Windows
```

Doğrula:

```bash
uv --version
```

### Sık gereken komutlar

```bash
# Ortamı sıfırdan kur (setup.sh'in yaptığı)
uv python install 3.11
uv venv --python 3.11
uv pip install -r requirements.txt

# Her şeyi güncelle
uv pip install -r requirements.txt --upgrade

# Sadece yt-dlp'yi güncelle — YouTube format değiştirince gereken şey budur
uv pip install --upgrade yt-dlp

# Ne kurulu?
uv pip list

# Ortamı tamamen sil ve baştan kur
rm -rf .venv && ./setup.sh
```

### NVIDIA ekran kartı

Varsayılan `torch` tekerleği Linux ve Windows'ta yalnızca CPU. CUDA için:

```bash
uv pip install -r requirements-gpu.txt
```

Apple Silicon'da bir şey yapmana gerek yok — Metal desteği varsayılan tekerlekte
geliyor. Uygulama açılışta hangi cihazı seçtiğini log'a yazıyor.

### Disk yer açma

uv indirdiği her şeyi ortak bir önbellekte tutuyor. Yer daralırsa:

```bash
uv cache clean
```

Bu sadece önbelleği siler; kurulu ortam çalışmaya devam eder.

---

## English

### Why uv

Encore's dependencies are heavy — torch, demucs and PySide6 together are a few
hundred megabytes. uv resolves and installs them substantially faster than pip
and keeps downloads in a machine-wide cache, so a second project sharing the
same packages does not re-download them. It can also install Python itself,
which is why `setup.sh` can promise 3.11 without you having to arrange it.

### Installing uv

`./setup.sh` installs it if missing. By hand:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # macOS / Linux
irm https://astral.sh/uv/install.ps1 | iex          # Windows PowerShell
```

### The commands worth knowing

```bash
# Recreate the environment from scratch — what setup.sh does
uv python install 3.11
uv venv --python 3.11
uv pip install -r requirements.txt

# Upgrade everything
uv pip install -r requirements.txt --upgrade

# Upgrade only yt-dlp — the usual fix when downloads start failing,
# because YouTube changes its formats often
uv pip install --upgrade yt-dlp

uv pip list                 # what is installed
uv cache clean              # reclaim disk; the venv keeps working
rm -rf .venv && ./setup.sh  # start over
```

### NVIDIA CUDA

The default `torch` wheel is CPU-only on Linux and Windows:

```bash
uv pip install -r requirements-gpu.txt
```

`pyproject.toml` already declares the PyTorch CUDA index for the `gpu` extra, so
`uv sync --extra gpu` works too if you prefer the project-file workflow.

On Apple Silicon there is nothing to do — Metal support ships in the default
wheel. Either way, the app logs which device it chose at start-up.

### If you would rather not use uv

Nothing in Encore depends on it. Plain pip works:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m karaoke_app.main
```

`setup.sh` is a convenience, not a requirement.
