"""Stage 5 label search: tally the VMD Forest State Register (MVR) open data (data.gov.lv,
"Meža valsts reģistra meža dati", CC0) without unpacking it to disk.

The archives are 7z; the Windows built-in `tar.exe` (libarchive) streams each .dbf member to
stdout, only the attribute table is read (no geometry). Per compartment the register keeps only
the LAST cut (P_CIRP / P_CIRG) and the current damage per species (BV / BA); see
docs/RM_5_EFDA_ANALIZE.md section 7.

    python scripts/rm_mvr_scan.py cache/vmd_mvr/centra.7z output/rm5_label_search
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


def members(archive: Path) -> list[str]:
    out = subprocess.run([TAR, "-tf", str(archive)], capture_output=True, text=True, check=True).stdout
    return [m for m in out.split() if m.endswith(".dbf")]


def scan(archive: Path, member: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(cuts: last cut method x year -> n, ha), (damage: BV code x BA code -> n, ha)."""
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
    for _ in range(n):
        r = f.read(rl)
        if len(r) < rl:
            break
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
    p.wait()
    c = pd.DataFrame([{"p_cirp": a, "p_cirg": b, "n": v, "ha": cut_ha[(a, b)]} for (a, b), v in cuts.items()])
    d = pd.DataFrame([{"bv": a, "ba": b, "n": v, "ha": dmg_ha[(a, b)]} for (a, b), v in dmg.items()])
    for t in (c, d):
        t["member"] = member
        t["records"] = n
    return c, d


def main() -> None:
    archive, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    cs, ds = [], []
    for m in members(archive):
        c, d = scan(archive, m)
        print(m, int(c["records"].iloc[0]), "records")
        cs.append(c)
        ds.append(d)
    stem = archive.stem
    pd.concat(cs).to_csv(out / f"mvr_{stem}_last_cut.csv", index=False)
    pd.concat(ds).to_csv(out / f"mvr_{stem}_damage.csv", index=False)


if __name__ == "__main__":
    main()
