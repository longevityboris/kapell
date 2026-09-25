#!/usr/bin/env python3
"""Extract selected members of a large remote ZIP without downloading all of it.

Usage::

    python3 fetch_zip_members.py URL DEST PATTERN [PATTERN ...] [--list] [--strip N]

``PATTERN`` is an ``fnmatch`` pattern matched against member names (e.g.
``*/SetC_DenseKH_LSOrchestra/Data/Omni/S1R163.wav``). Matching members are
written under ``DEST`` with their paths preserved (minus ``--strip N`` leading
components). ``--list`` prints the matching names and sizes and extracts nothing.

The server must honour HTTP range requests (Zenodo does). ``zipfile`` reads
the central directory from the end of the file and then each wanted member,
so only those bytes travel: about 7 MB instead of the 986 MB Detmold archive.
CRC-32 of every extracted member is checked by ``zipfile``.
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "ricercar-setup/1.0 (range reader)"}


class HTTPRangeFile(io.RawIOBase):
    def __init__(self, url: str):
        self.url = url
        req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            if r.status != 206:
                raise OSError(f"{url}: server ignores range requests (HTTP {r.status})")
            self.size = int(r.headers["Content-Range"].split("/")[-1])
        self.pos = 0
        self.requests = 0
        self.bytes = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=io.SEEK_SET):
        self.pos = {io.SEEK_SET: off, io.SEEK_CUR: self.pos + off, io.SEEK_END: self.size + off}[whence]
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.size, self.pos + len(b)) - 1
        req = urllib.request.Request(self.url, headers={**UA, "Range": f"bytes={self.pos}-{end}"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                break
            except OSError:
                if attempt == 3:
                    raise
        n = len(data)
        b[:n] = data
        self.pos += n
        self.requests += 1
        self.bytes += n
        return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("dest", type=Path)
    ap.add_argument("patterns", nargs="+")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--strip", type=int, default=0, help="drop N leading path components")
    args = ap.parse_args()

    raw = HTTPRangeFile(args.url)
    fh = io.BufferedReader(raw, buffer_size=1 << 20)
    with zipfile.ZipFile(fh) as z:
        infos = [i for i in z.infolist() if not i.is_dir() and any(fnmatch.fnmatch(i.filename, p) for p in args.patterns)]
        if not infos:
            print(f"no member matches {args.patterns}", file=sys.stderr)
            return 1
        for i in infos:
            if args.list:
                print(f"{i.file_size:>12d}  {i.filename}")
                continue
            parts = Path(i.filename).parts[args.strip:]
            out = args.dest.joinpath(*parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(out.suffix + ".part")
            with z.open(i) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            tmp.replace(out)
            print(f"extracted {out} ({i.file_size} bytes)")
    print(f"archive {raw.size} bytes; fetched {raw.bytes} bytes in {raw.requests} range requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
