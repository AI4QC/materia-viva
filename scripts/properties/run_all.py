#!/usr/bin/env python3
"""Production driver: run every source pipeline + load in dependency order.

Order:
1. matbench-discovery first (its MP-2023 snapshot fingerprints bridge legacy
   numeric mp ids into the match map for every later id match);
2. mp_bridge.py;
3. all small/medium sources sequentially (adapt -> hash -> match -> load);
4. the huge sources whose adapt stages were started separately in the
   background (alexandria, aflow) — hash/match/load once their staging files
   exist;
5. final scalar/space-group/family backfill.

Resumable: a source with an existing load_report.json is skipped; a source
with complete pipeline artifacts skips straight to load. Failures are logged
and the driver moves on.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORK = PROJECT_ROOT / "data" / "props_work"
LOGS = WORK / "_logs"
PYTHON = os.environ.get("MATERIAVIVA_PYTHON", sys.executable)

BRIDGE_FIRST = ["matbench-discovery"]

SMALL_MEDIUM = [
    "snumat",
    "materiae",
    "phonix",
    "novomag",
    "3dsc",
    "superband",
    "jarvis-specialized-structures",
    "jarvis-dft",
    "spse",
    "obelix",
    "elementa",
    "c2db",
    "2dmatpedia",
    "omdb-organic",
    "mc2d",
    "hadb",
    "hex-high-pressure",
    "sacada",
    "tcod",
    "amcsd",
    "ec-mof",
    "materials-cloud-archive-static",
    "odbx",
    "materials-project",
    "gnome",
    "hmof",
    "mof-carbon-capture",
    # wave 3
    "cmr-static",
    "fair-mofs",
    "mofx-db",
    "bidb",
    "aflow-prototypes",
    "rruff",
    "open-framework-aluminophosphate",
    "deem-zeolites",
]

HUGE = ["alexandria", "aflow"]


def run(command: list[str], log_path: Path) -> int:
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n===== {' '.join(command)} @ {time.strftime('%F %T')}\n")
        log.flush()
        process = subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT
        )
    return process.returncode


def artifacts_complete(source: str) -> bool:
    work = WORK / source
    return all(
        (work / name).exists()
        for name in ("matched.tsv.gz", "new_structs.jsonl.gz", "staging_props.tsv.gz")
    )


def missing_stages(source: str) -> list[str]:
    work = WORK / source
    stages = []
    if not all(
        (work / name).exists()
        for name in ("staging_props.tsv.gz", "id_matches.tsv.gz",
                     "staging_structs.jsonl.gz")
    ):
        stages.append("adapt")
    if stages or not (work / "hashes.tsv.gz").exists():
        stages.append("hash")
    if stages or not (work / "matched.tsv.gz").exists():
        stages.append("match")
    return stages


def process_source(source: str, nproc: int, status: dict) -> None:
    log_path = LOGS / f"{source}.log"
    work = WORK / source
    started = time.time()
    if (work / "load_report.json").exists():
        status[source] = {"state": "already-loaded"}
        print(f"[skip] {source}: already loaded", flush=True)
        return
    for stage in missing_stages(source):
        print(f"[pipeline] {source}: {stage}", flush=True)
        code = run(
            [PYTHON, "scripts/properties/pipeline.py", source, "--stage", stage,
             "--nproc", str(nproc)],
            log_path,
        )
        if code != 0:
            status[source] = {
                "state": f"pipeline-{stage}-failed", "log": str(log_path),
            }
            print(f"[FAIL] {source}: {stage} exited {code}", flush=True)
            return
    print(f"[load] {source}", flush=True)
    code = run([PYTHON, "scripts/properties/load.py", "load", source], log_path)
    if code != 0:
        status[source] = {"state": "load-failed", "log": str(log_path)}
        print(f"[FAIL] {source}: load exited {code}", flush=True)
        return
    status[source] = {
        "state": "done",
        "minutes": round((time.time() - started) / 60, 1),
    }
    print(f"[done] {source} ({status[source]['minutes']} min)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nproc", type=int, default=26)
    parser.add_argument(
        "--phase", choices=("bridge", "main", "huge", "backfill", "all"),
        default="all",
    )
    parser.add_argument("--sources", nargs="*", default=None,
                        help="explicit source list overriding the phase plan")
    args = parser.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    status_path = WORK / "run_status.json"
    status: dict = {}
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))

    def save() -> None:
        status_path.write_text(
            json.dumps(status, indent=2, sort_keys=True), encoding="utf-8"
        )

    if args.sources:
        plan = [("src", source) for source in args.sources]
    else:
        plan = []
        if args.phase in ("bridge", "all"):
            plan += [("src", source) for source in BRIDGE_FIRST]
            plan.append(("bridge", None))
        if args.phase in ("main", "all"):
            plan += [("src", source) for source in SMALL_MEDIUM]
        if args.phase in ("huge", "all"):
            plan += [("src", source) for source in HUGE]
        if args.phase in ("backfill", "all"):
            plan.append(("backfill", None))

    for kind, source in plan:
        if kind == "src":
            process_source(source, args.nproc, status)
            save()
        elif kind == "bridge":
            code = run(
                [PYTHON, "scripts/properties/mp_bridge.py"], LOGS / "mp_bridge.log"
            )
            status["_mp_bridge"] = {"state": "done" if code == 0 else "failed"}
            print(f"[bridge] exit {code}", flush=True)
            save()
        elif kind == "backfill":
            code = run(
                [PYTHON, "scripts/properties/load.py", "backfill"],
                LOGS / "backfill.log",
            )
            status["_backfill"] = {"state": "done" if code == 0 else "failed"}
            print(f"[backfill] exit {code}", flush=True)
            save()

    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
