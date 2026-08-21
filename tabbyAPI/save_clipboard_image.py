"""Save a clipboard image to a file on Windows, WSL, or Linux.

Usage:
  python save_clipboard_image.py [path]
Default path is screenshot.png in the current directory.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def is_wsl() -> bool:
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "microsoft" in text.lower()


def which(name: str) -> str | None:
    return shutil.which(name)


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def to_windows_path(path: Path) -> str:
    wslpath = which("wslpath")
    if wslpath:
        result = run([wslpath, "-w", str(path)])
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    posix = path.resolve().as_posix()
    if posix.startswith("/mnt/") and len(posix) > 6 and posix[5].isalpha() and posix[6] == "/":
        drive = posix[5].upper()
        rest = posix[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    raise SystemExit(f"Cannot convert {path} to a Windows path")


def save_via_powershell(dest: Path, powershell: str) -> None:
    suffix = dest.suffix.lower()
    fmt = {
        ".jpg": "Jpeg",
        ".jpeg": "Jpeg",
        ".bmp": "Bmp",
        ".gif": "Gif",
        ".png": "Png",
    }.get(suffix, "Png")
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".gif"}:
        dest = dest.with_suffix(".png")
        fmt = "Png"

    win_dest = str(dest) if sys.platform == "win32" else to_windows_path(dest)
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$dest = {win_dest!r}
$dir = Split-Path -Parent $dest
if ($dir) {{ New-Item -ItemType Directory -Force -Path $dir | Out-Null }}
$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $img) {{
    throw 'Clipboard has no image. Copy the picture (Ctrl+C), then run this again.'
}}
$img.Save($dest, [System.Drawing.Imaging.ImageFormat]::{fmt})
Write-Output $dest
"""
    result = run([powershell, "-NoProfile", "-STA", "-Command", script])
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout or "clipboard save failed").strip())


def save_via_linux(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if which("wl-paste"):
        result = subprocess.run(
            ["wl-paste", "--type", "image/png"],
            stdout=dest.open("wb"),
            stderr=subprocess.PIPE,
            timeout=20,
        )
        if result.returncode == 0 and dest.exists() and dest.stat().st_size >= 32:
            return
    if which("xclip"):
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            stdout=dest.open("wb"),
            stderr=subprocess.PIPE,
            timeout=20,
        )
        if result.returncode == 0 and dest.exists() and dest.stat().st_size >= 32:
            return
    raise SystemExit(
        "No image on the Linux clipboard. Install xclip or wl-clipboard, "
        "copy the picture, then retry."
    )


def save(dest: Path) -> Path:
    dest = dest.expanduser()
    if not dest.is_absolute():
        dest = Path.cwd() / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".gif"}:
        dest = dest.with_suffix(".png")

    if sys.platform == "win32":
        save_via_powershell(dest, "powershell")
    elif is_wsl() and which("powershell.exe"):
        save_via_powershell(dest, "powershell.exe")
    else:
        save_via_linux(dest)

    if not dest.exists() or dest.stat().st_size < 32:
        raise SystemExit("Clipboard save produced no image file.")
    print(dest)
    return dest


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("screenshot.png")
    save(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
