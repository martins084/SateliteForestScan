"""Extract selected members of EFDA country archives with HTTP range requests (no full download).

    python scripts/rm_efda_extract.py            # members used in stage 5 (configs/rm_latvia.yaml)

Writes cache/efda/<version>/<archive>/<member> and cache/efda/download_log.json (size, sha256,
date). zipfile verifies the CRC of every member. v3.0: the Latvian rasters are in
Lithuania.zip (archives swapped in the release; `mezasargs-risk labels` checks the extent).
The probability layers (~0.8-0.9 GB per archive) and v3.0 severity are not extracted.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path("cache/efda")
JOBS = {
    ("v3.0", "Lithuania.zip", "https://zenodo.org/records/21722408/files/Lithuania.zip?download=1"):
        ["annual_disturbance_lithuania_v30.tif", "disturbance_agent_lithuania_v30.tif",
         "number_disturbances_lithuania_v30.tif", "disturbance_agent_aggregated_lithuania_v30.tif",
         "latest_disturbance_lithuania_v30.tif", "forestlanduse_mask_lithuania_v30.tif"],
    ("v2.1.1", "latvia.zip", "https://zenodo.org/records/13333034/files/latvia.zip?download=1"):
        ["disturbance_agent_1985_2023_latvia.tif", "disturbance_agent_aggregated_latvia.tif",
         "forest_mask_latvia.tif"],
}


class RangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests."""

    def __init__(self, url: str):
        h = requests.head(url, allow_redirects=True, timeout=60)
        h.raise_for_status()
        self.url, self.size, self.pos, self.got = h.url, int(h.headers["Content-Length"]), 0, 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def readinto(self, b):
        end = min(self.pos + len(b), self.size) - 1
        if end < self.pos:
            return 0
        r = requests.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}, timeout=120)
        r.raise_for_status()
        b[:len(r.content)] = r.content
        self.pos += len(r.content)
        self.got += len(r.content)
        return len(r.content)


def main() -> None:
    log = []
    for (ver, zname, url), members in JOBS.items():
        rf = RangeFile(url)
        z = zipfile.ZipFile(io.BufferedReader(rf, 1 << 22))
        out = ROOT / ver / zname
        out.mkdir(parents=True, exist_ok=True)
        for m in members:
            dst = out / m
            if not dst.exists():
                part = dst.with_suffix(".part")
                with z.open(m) as src, open(part, "wb") as f:
                    shutil.copyfileobj(src, f, 1 << 22)
                part.rename(dst)
            log.append({"version": ver, "archive": zname, "url": url, "member": m,
                        "bytes": dst.stat().st_size,
                        "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
                        "checked": time.strftime("%Y-%m-%d")})
            print(f"{ver}/{zname}/{m}: {dst.stat().st_size / 1e6:.1f} MB")
        print(f"{zname}: {rf.got / 1e6:.1f} MB transferred")
    (ROOT / "download_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
