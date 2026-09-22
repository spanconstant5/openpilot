#!/usr/bin/env python3
"""Summarize passive Corolla TSS3 signer evidence in local rlogs.

This tool only reads saved logs. It does not connect to a car or send CAN.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile


WATCH_IDS = (0x00F, 0x0D7, 0x0B6, 0x08A, 0x160, 0x1A0, 0x777, 0x7A1, 0x7A9)
ACTUATION_IDS = {0x0B6, 0x08A, 0x777}


def local_rlogs(source: Path, temporary: Path) -> list[Path]:
  if source.is_dir():
    return sorted(source.rglob("rlog.zst")) + sorted(source.rglob("rlog"))
  if source.name in ("rlog.zst", "rlog"):
    return [source]
  if source.suffix.lower() != ".zip":
    raise ValueError("expected a route directory, rlog, or ZIP of rlogs")

  paths = []
  with zipfile.ZipFile(source) as archive:
    members = [m for m in archive.infolist() if not m.is_dir() and Path(m.filename).name in ("rlog.zst", "rlog")]
    if len(members) > 100:
      raise ValueError("archive contains too many rlogs")
    for index, member in enumerate(members):
      if member.file_size > 1_000_000_000:
        raise ValueError("archive contains an oversized rlog")
      source_name = Path(member.filename.replace("\\", "/")).parent.name
      if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", source_name):
        source_name = "unknown-segment"
      path = temporary / f"{index:03d}-{source_name}" / Path(member.filename).name
      path.parent.mkdir(parents=True, exist_ok=True)
      with archive.open(member) as src, path.open("wb") as dst:
        shutil.copyfileobj(src, dst)
      paths.append(path)
  return paths


def summarize_segment(messages, name: str) -> dict:
  counts = Counter()
  can_counts = Counter()
  send_counts = Counter()
  safety = Counter()
  params = []
  versions = set()
  card_running_samples = 0
  card_last_running = None

  for msg in messages:
    kind = msg.which()
    if kind in ("can", "sendcan"):
      for frame in getattr(msg, kind):
        if frame.address in WATCH_IDS:
          key = f"0x{frame.address:03X}/bus{frame.src}/len{len(frame.dat)}"
          (can_counts if kind == "can" else send_counts)[key] += 1
    elif kind == "carParams":
      cp = msg.carParams
      params.append({
        "fingerprint": str(cp.carFingerprint),
        "source": str(cp.fingerprintSource),
        "passive": bool(cp.passive),
        "dashcam_only": bool(cp.dashcamOnly),
        "safety": [str(s.safetyModel) for s in cp.safetyConfigs],
      })
    elif kind == "pandaStates":
      for panda in msg.pandaStates:
        safety[str(panda.safetyModel)] += 1
    elif kind == "managerState":
      card_process = next((p for p in msg.managerState.processes if p.name == "card"), None)
      if card_process is not None:
        card_running_samples += bool(card_process.running)
        card_last_running = bool(card_process.running)
    elif kind == "initData":
      versions.add((str(msg.initData.gitBranch), str(msg.initData.gitCommit)))
    counts[kind] += 1

  rx_b6 = sum(n for key, n in can_counts.items() if key.startswith("0x0B6/bus") and int(key.split("/bus")[1].split("/")[0]) < 128)
  tx_actuation = sum(n for key, n in send_counts.items() if int(key[2:5], 16) in ACTUATION_IDS)
  return {
    "segment": name,
    "versions": [{"branch": branch, "commit": commit} for branch, commit in sorted(versions)],
    "car_params": params[-1] if params else None,
    "car_params_events": counts["carParams"],
    "car_state_events": counts["carState"],
    "card_manager_samples": counts["managerState"],
    "card_running_samples": card_running_samples,
    "card_last_running": card_last_running,
    "panda_safety_samples": dict(sorted(safety.items())),
    "watched_can": dict(sorted(can_counts.items())),
    "watched_sendcan": dict(sorted(send_counts.items())),
    "native_b6_rx_count": rx_b6,
    "actuation_send_count": tx_actuation,
  }


def summarize(paths: list[Path]) -> dict:
  import zstandard as zstd
  from openpilot.cereal import log

  segments = []
  for path in paths:
    with path.open("rb") as f:
      if path.suffix == ".zst":
        with zstd.ZstdDecompressor().stream_reader(f) as reader:
          data = reader.read()
      else:
        data = f.read()
    segments.append(summarize_segment(log.Event.read_multiple_bytes(data), str(path.parent.name)))
  return {
    "schema": "corolla-tss3-passive-log-check-v1",
    "segments": segments,
    "passive_corolla_startup_observed": any(
      s["car_params"] is not None
      and s["car_params"]["fingerprint"] == "TOYOTA_COROLLA_TSS3"
      and s["car_params"]["passive"]
      and s["car_params"]["dashcam_only"]
      and s["car_state_events"] > 0
      for s in segments
    ),
    "native_b6_observed": any(s["native_b6_rx_count"] for s in segments),
    "host_actuation_observed": any(s["actuation_send_count"] for s in segments),
    "interpretation": "Presence checks only; they do not qualify a signer or prove EPS acceptance.",
  }


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("source", type=Path, help="local rlog, route directory, or ZIP")
  parser.add_argument("--output", type=Path, help="write JSON report here (default: stdout)")
  args = parser.parse_args()
  with tempfile.TemporaryDirectory(prefix="corolla-tss3-log-check-") as work:
    paths = local_rlogs(args.source, Path(work))
    if not paths:
      parser.error("no rlogs found")
    report = summarize(paths)
  output = json.dumps(report, indent=2, sort_keys=True) + "\n"
  if args.output:
    args.output.write_text(output, encoding="utf-8")
  else:
    print(output, end="")


if __name__ == "__main__":
  main()
