"""Golden regression: with the v0.2-kalsnava configuration the current s2forest code must
reproduce the v0.2-kalsnava detection outputs exactly (tests/golden/kalsnava_v02.json, made
from a run of the tagged code on the same cached data; see scripts/golden_s2forest.py).

Needs the local Kalsnava cache (cache/), takes ~10 min -> marker `golden`, not run by default:
    python -m uv run pytest -m golden
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"

pytestmark = pytest.mark.golden


def _golden_module():
    spec = importlib.util.spec_from_file_location("golden_s2forest", ROOT / "scripts" / "golden_s2forest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_detection_identical_to_v02(tmp_path):
    cfg = yaml.safe_load((GOLDEN / "kalsnava_v02.yaml").read_text(encoding="utf-8"))
    cache = (GOLDEN / cfg["cache_dir"]).resolve()
    if not cache.exists():
        pytest.skip("local Kalsnava cache not available")
    cfg["aoi"] = str((GOLDEN / cfg["aoi"]).resolve())
    cfg["cache_dir"] = str(cache)
    cfg["output_dir"] = str(tmp_path)
    cfg["reference"]["path"] = str((GOLDEN / cfg["reference"]["path"]).resolve())
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    cli = [sys.executable, "-c", "from s2forest.cli import app; app()"]
    for args in (["indices", str(path)], ["detect", "--no-closeups", str(path)]):
        subprocess.run(cli + args, check=True, capture_output=True)
    g = _golden_module()
    diffs = g.compare(g.snapshot(tmp_path / cfg["run_name"]),
                      json.loads((GOLDEN / "kalsnava_v02.json").read_text(encoding="utf-8")))
    assert not diffs, "\n".join(diffs)
