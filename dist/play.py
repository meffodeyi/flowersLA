import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import shutil
import struct
import sys
import time
import zipfile


@contextmanager
def console():
    restore = None
    if os.name == "nt" and sys.stdout.isatty():
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(sys.stdout.fileno()))
        mode = wintypes.DWORD()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.SetConsoleMode(handle, mode.value | 0x0005):
            raise OSError("Open this folder in Windows Terminal and try again.")
        restore = lambda: kernel.SetConsoleMode(handle, mode.value)
    try:
        yield
    finally:
        if restore:
            restore()


def show(data):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


@lru_cache(maxsize=8192)
def color(rgb):
    return b"\x1b[38;2;%d;%d;%dm" % tuple(rgb)


def layout(source_w, source_h):
    cols, rows = shutil.get_terminal_size((80, 24))
    # Leave room for the command prompt and avoid wrapping at the right edge.
    room_w, room_h = max(1, cols - 1), max(1, rows - 2)
    scale = min(room_w / source_w, room_h / source_h)
    w = max(1, min(room_w, round(source_w * scale)))
    h = max(1, min(room_h, round(source_h * scale)))
    return w, h, (cols - w) // 2 + 1, (room_h - h) // 2 + 1


@lru_cache(maxsize=1)
def sampling(sw, sh, w, h):
    xs = [int((x + .5) * sw / w) * 4 for x in range(w)]
    ys = [int((y + .5) * sh / h) * sw * 4 for y in range(h)]
    return xs, ys


def draw(frame, sw, sh, box, clear):
    w, h, left, top = box
    xs, ys = sampling(sw, sh, w, h)
    out = bytearray(b"\x1b[0m\x1b[2J" if clear else b"")
    out.extend(b"\x1b[48;2;0;0;0m")
    last = None
    for y, start in enumerate(ys, top):
        out.extend(b"\x1b[%d;%dH" % (y, left))
        for x in xs:
            i = start + x
            glyph = frame[i]
            if glyph != 32:
                rgb = frame[i + 1:i + 4]
                if rgb != last:
                    out.extend(color(rgb))
                    last = rgb
            out.append(glyph)
    show(out)


def play():
    folder = Path(__file__).resolve().parent
    data = folder / "data.bin"
    if not data.is_file():
        if not (folder / "build.py").is_file():
            raise FileNotFoundError("Файл data.bin должен лежать рядом с play.py.")
        data = folder / "dist" / "data.bin"
        if not data.is_file():
            raise FileNotFoundError("Сначала соберите проект командой python3 build.py.")
    with zipfile.ZipFile(data) as archive:
        w, h, n = struct.unpack("<III", archive.read("layout"))
        times = struct.unpack(f"<{n + 1}d", archive.read("clock"))
        size = w * h * 4
        with archive.open("cells") as frames, console():
            previous = None
            try:
                show(b"\x1b[?25l")
                start = time.monotonic()
                for i in range(n):
                    frame = frames.read(size)
                    if len(frame) != size:
                        raise ValueError("Incomplete data file.")
                    now = time.monotonic() - start
                    if 0 < i < n - 1 and now >= times[i + 1]:
                        continue
                    time.sleep(max(0, times[i] - now))
                    box = layout(w, h)
                    draw(frame, w, h, box, previous != box)
                    previous = box
                time.sleep(max(0, start + times[-1] - time.monotonic()))
            finally:
                row = previous[1] + previous[3] if previous else 1
                show(b"\x1b[0m\x1b[%d;1H\x1b[?25h" % row)


if __name__ == "__main__":
    try:
        play()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, KeyError, struct.error, zipfile.BadZipFile) as error:
        sys.exit(str(error))
