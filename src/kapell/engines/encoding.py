"""Portable AAC export; an installed afconvert may have no AAC codec available."""
import shutil
import subprocess
from pathlib import Path

from kapell.commands import KapellError


def encode_aac(wav: Path, m4a: Path) -> None:
    commands = []
    if shutil.which("afconvert"):
        commands.append(["afconvert", "-f", "m4af", "-d", "aac", "-b", "256000", str(wav), str(m4a)])
    if shutil.which("ffmpeg"):
        commands.append(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                         "-c:a", "aac", "-b:a", "256k", str(m4a)])
    errors = []
    for cmd in commands:
        m4a.unlink(missing_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and m4a.is_file() and m4a.stat().st_size:
            return
        errors.append(f"{cmd[0]}: {result.stderr.strip()[-200:]}")
    m4a.unlink(missing_ok=True)
    raise KapellError("encoder_unavailable", "; ".join(errors) or "no AAC encoder installed",
                      "install ffmpeg; run kapell doctor", 2)
