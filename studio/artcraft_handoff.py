"""Stage a publicly shareable illustration from the completed Studio run."""
import argparse
import json
import shutil
from pathlib import Path

from .artcraft import write_json
from .scan import clamscan
from .util import ID_RE, sha256_file


def stage(runs, actions_url, target):
    matches = []
    for manifest in runs.glob("*/run.json"):
        result = json.loads(manifest.read_text())
        if (actions_url not in result.get("actions_runs", [])
                or result.get("status") != "done" or result.get("publish") is not True
                or result.get("has_private_inputs") is not False
                or not ID_RE.fullmatch(manifest.parent.name)):
            continue
        for stage_id, state in reversed(list(result["stages"].items())):
            image = (state.get("best") or {}).get("image")
            if not image or state.get("private_inputs") != []:
                continue
            source = (manifest.parent / image).resolve()
            if source.is_relative_to(manifest.parent.resolve()) and source.suffix == ".png" and source.is_file():
                matches.append((manifest.parent.name, stage_id, source))
                break

    if not matches:
        return
    run_id, stage_id, source = max(matches)
    scanned = clamscan([source])
    if scanned["status"] != "SAFETY_CHECK_OK":
        raise RuntimeError(scanned["status"])
    target.mkdir(exist_ok=True)
    shutil.copyfile(source, target / "source.png")
    write_json(target / "source.json", {
        "run_id": run_id, "stage": stage_id, "actions_url": actions_url,
        "sha256": sha256_file(source), "scan": scanned["status"],
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("url")
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    stage(args.runs, args.url, args.target)
