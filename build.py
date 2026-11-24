"""Build the portable animation from a video in this directory."""
import argparse
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".mpg", ".mpeg", ".mts", ".m2ts", ".wmv"}
FILES = {"play.py", "play.cmd", "data.bin"}
RAMP = b" .,:;irsXA253hMHGS#9B&@"
# Lift shadow detail while keeping genuinely black pixels empty.
DENSITY = bytes(RAMP[round((i / 255) ** 0.75 * (len(RAMP) - 1))] for i in range(256))
INK = bytes(min(255, round(i * 1.12 + 8)) for i in range(256))


def select_video(name):
    if name:
        path = (ROOT / name).resolve()
        if path.parent != ROOT or not path.is_file():
            raise ValueError("Укажите видеофайл из корня проекта.")
        return path
    videos = sorted(p for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if len(videos) != 1:
        names = ", ".join(p.name for p in videos)
        raise ValueError("Положите один ролик в корень или выполните python3 build.py \"имя файла\". " + names)
    return videos[0]


def encoder():
    for path in (os.environ.get("FFMPEG"), shutil.which("ffmpeg"),
                 "/Applications/BlueStacks.app/Contents/MacOS/ffmpeg"):
        if path and os.access(path, os.X_OK):
            return path
    raise ValueError("Для сборки установите FFmpeg командой brew install ffmpeg.")


def cells(rgb):
    out = bytearray(len(rgb) // 3 * 4)
    for offset in range(3):
        out[offset + 1::4] = rgb[offset::3].translate(INK)
    out[0::4] = bytes(DENSITY[(54*r + 183*g + 19*b) >> 8]
                      for r, g, b in zip(rgb[::3], rgb[1::3], rgb[2::3]))
    return out


def convert(video, dest, log):
    # dar includes non-square source pixels. The grid assumes 1:2 terminal cells.
    scale = ("scale=w='max(1,round(min(192,192*dar)))':"
             "h='max(1,round(min(96,96/dar)))':flags=area,setsar=1,format=rgb24,showinfo=checksum=0")
    cmd = [encoder(), "-nostdin", "-hide_banner", "-nostats", "-i", str(video),
           "-map", "0:V:0", "-vf", scale, "-fps_mode", "passthrough",
           "-c:v", "ppm", "-f", "image2pipe", "pipe:1"]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        with log.open("wb") as errors, subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors) as proc:
            count = 0
            shape = None
            try:
                with archive.open("cells", "w", force_zip64=True) as stream:
                    while magic := proc.stdout.readline():
                        dims = tuple(map(int, proc.stdout.readline().split()))
                        if magic != b"P6\n" or len(dims) != 2 or proc.stdout.readline() != b"255\n":
                            raise ValueError("Некорректный поток кадров.")
                        if shape and dims != shape:
                            raise ValueError("Размер изображения изменился внутри ролика.")
                        shape = dims
                        rgb = proc.stdout.read(dims[0] * dims[1] * 3)
                        if len(rgb) != dims[0] * dims[1] * 3:
                            raise ValueError("Неполный кадр.")
                        stream.write(cells(rgb))
                        count += 1
            finally:
                proc.stdout.close()
                if proc.poll() is None and not count:
                    proc.terminate()
        if proc.returncode or not count:
            with video.open("rb") as source:
                if source.read(7) == b"#EXTM3U":
                    raise ValueError(
                        f"«{video.name}» содержит плейлист со ссылками. "
                        "Для сборки скачайте сам ролик в MP4 или MOV и укажите его имя."
                    )
            raise ValueError(log.read_text(errors="replace")[-1500:])
        times = []
        duration = 0
        with log.open(errors="replace") as lines:
            for line in lines:
                if "showinfo" in line and " n:" in line:
                    match = re.search(r'pts_time:(\S+)', line)
                    times.append(float(match[1]))
                    match = re.search(r'duration_time:(\S+)', line)
                    duration = float(match[1]) if match and match[1] != "N/A" else 0
        if len(times) != count or not all(map(math.isfinite, times)) or times != sorted(times):
            raise ValueError("Не удалось прочитать время показа кадров.")
        if duration <= 0:
            duration = (times[-1] - times[-2]) if count > 1 else 1/25
        times.append(times[-1] + duration)
        clock = [t - times[0] for t in times]
        archive.writestr("layout", struct.pack("<III", *shape, count))
        archive.writestr("clock", struct.pack(f"<{len(clock)}d", *clock))
        return count, clock[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", nargs="?")
    video = select_video(parser.parse_args().video)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    if dist.is_symlink() or any(p.name not in FILES or p.is_symlink() or not p.is_file()
                                for p in dist.iterdir()):
        raise ValueError("В dist есть посторонние файлы. Переместите их перед сборкой.")
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        stage = Path(tmp)
        count, duration = convert(video, stage / "data.bin", stage / "decode.log")
        for name in ("play.py", "play.cmd"):
            shutil.copyfile(ROOT / name, stage / name)
        for name in sorted(FILES):
            (stage / name).replace(dist / name)
    print(f"Готово: dist/ — {count} кадров, {duration:.2f} с.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
