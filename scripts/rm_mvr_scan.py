"""Stage 5 label search: tally the VMD Forest State Register (MVR) open data (data.gov.lv,
"Meža valsts reģistra meža dati", CC0) without unpacking it to disk.

The archives are 7z; the Windows built-in `tar.exe` (libarchive) streams each .dbf member to
stdout, only the attribute table is read (no geometry). Per compartment the register keeps only
the LAST cut (P_CIRP / P_CIRG) and the current damage per species (BV / BA); see
docs/RM_5_EFDA_ANALIZE.md section 7.

    python scripts/rm_mvr_scan.py cache/vmd_mvr/centra.7z output/rm5_label_search

Completeness check per district: records in the DBF header = records read from the stream =
records in the .shx index ((size - 100) / 8).
"""

from __future__ import annotations

import collections
import struct
import subprocess
import sys
from pathlib import Path

import pandas as pd

TAR = r"C:\Windows\System32\tar.exe"
SPECIES = ("10", "11", "12", "13", "14")


def listing(archive: Path) -> dict[str, int]:
    """Member name -> uncompressed size (bytes)."""
    out = subprocess.run([TAR, "-tvf", str(archive)], capture_output=True, text=True, check=True).stdout
    sizes = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 9 and not parts[0].startswith("d"):
            sizes[parts[-1]] = int(parts[4])
    return sizes


def scan(archive: Path, member: str) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """(cuts: last cut method x year -> n, ha), (damage: BV code x BA code -> n, ha),
    records in the DBF header, records actually read."""
    p = subprocess.Popen([TAR, "-xOf", str(archive), member], stdout=subprocess.PIPE)
    f = p.stdout
    h = f.read(32)
    n = struct.unpack("<I", h[4:8])[0]
    hl, rl = struct.unpack("<HH", h[8:12])
    rest = f.read(hl - 32)
    fields, i, pos = {}, 0, 1
    while rest[i] != 0x0D:
        name = rest[i:i + 11].split(b"\0")[0].decode("latin1").lower()
        fields[name] = (pos, rest[i + 16])
        pos += rest[i + 16]
        i += 32

    def get(r, k):
        s, ln = fields[k]
        return r[s:s + ln].decode("utf8", "replace").strip().split(".")[0]

    cuts, dmg = collections.Counter(), collections.Counter()
    cut_ha, dmg_ha = collections.Counter(), collections.Counter()
    read = 0
    for _ in range(n):
        r = f.read(rl)
        if len(r) < rl:
            break
        read += 1
        s, ln = fields["nog_plat"]
        ha = float(r[s:s + ln] or 0)
        k = (get(r, "p_cirp"), get(r, "p_cirg"))
        cuts[k] += 1
        cut_ha[k] += ha
        # a compartment counts once per damage code (any species of the 1st storey)
        for code, ext in {(get(r, f"bv{s_}"), get(r, f"ba{s_}")) for s_ in SPECIES}:
            if code != "0":
                dmg[(code, ext)] += 1
                dmg_ha[(code, ext)] += ha
    f.read()
    p.wait()
    c = pd.DataFrame([{"p_cirp": a, "p_cirg": b, "n": v, "ha": cut_ha[(a, b)]} for (a, b), v in cuts.items()])
    d = pd.DataFrame([{"bv": a, "ba": b, "n": v, "ha": dmg_ha[(a, b)]} for (a, b), v in dmg.items()])
    for t in (c, d):
        t["member"] = member
        t["records"] = n
    return c, d, n, read


def main() -> None:
    archive, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    cs, ds, checks = [], [], []
    sizes = listing(archive)
    for m in sorted(k for k in sizes if k.endswith(".dbf")):
        c, d, n, read = scan(archive, m)
        shx = sizes.get(m[:-4] + ".shx")
        n_shx = (shx - 100) // 8 if shx else None      # shapefile index: 100-byte header + 8 bytes/record
        ok = n == read == n_shx
        checks.append({"member": m, "dbf_header": n, "dbf_read": read, "shx_records": n_shx, "ok": ok})
        print(m, f"dbf header {n}, read {read}, shx {n_shx}", "OK" if ok else "MISMATCH")
        cs.append(c)
        ds.append(d)
    stem = archive.stem
    pd.DataFrame(checks).to_csv(out / f"mvr_{stem}_record_check.csv", index=False)
    pd.concat(cs).to_csv(out / f"mvr_{stem}_last_cut.csv", index=False)
    pd.concat(ds).to_csv(out / f"mvr_{stem}_damage.csv", index=False)


if __name__ == "__main__":
    main()
