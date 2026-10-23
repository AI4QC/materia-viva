#!/usr/bin/env python3
"""Upload the two MateriaViva releases to Hugging Face unattended, then verify them.

It runs as the user unit ``~/.config/systemd/user/materiaviva-hf-upload.service``
(enabled, Restart=on-failure), so no terminal or Claude session owns it and a reboot
resumes it; once everything verifies it writes ``data/hf-release-logs/DONE`` and the
unit stops starting. The outcome also goes out as a desktop notification.

    systemctl --user status materiaviva-hf-upload
    journalctl --user -u materiaviva-hf-upload      # driver log
    cat data/hf-release-logs/STATUS.md              # progress and verification
    rm data/hf-release-logs/DONE && systemctl --user start materiaviva-hf-upload   # append later tasks

Jobs run one after the other (the uplink is ~1.5 MB/s; two at once only slow each
other down), the riskiest first: the 23 GB ``materials.sqlite``, the rest of the full
index (predictions, card, docs), then the open release. Each job is verified file by
file against the Hub (size + sha256 for LFS files, git blob id for the rest).

The transfer itself is ``hf_upload_resilient.py`` (classic LFS with timeouts and
patient per-part retries -- see there for why). This file only supervises it: an
attempt that has finished no upload request, logged no retry and changed no counter
for ``STALL`` seconds is killed and restarted (files already uploaded are kept; a
half-sent multipart file is not, so a retrying attempt is never killed). The private
storage quota (403) or a 401 stops the job instead: retrying cannot fix it.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from huggingface_hub import HfApi
from huggingface_hub.hf_api import RepoFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS = PROJECT_ROOT / "data" / "hf-release-logs"
UPLOADER = PROJECT_ROOT / "scripts" / "hf_upload_resilient.py"
SQLITE = "index/materials.sqlite"
JOBS = [
    {"name": "full-sqlite", "repo": "AI4QC/MateriaViva", "folder": "data/hf-upload", "include": [SQLITE]},
    {"name": "full-rest", "repo": "AI4QC/MateriaViva", "folder": "data/hf-upload", "exclude": [SQLITE]},
    {"name": "open", "repo": "AI4QC/MateriaViva-Open", "folder": "data/open-release/hf"},
]
STALL = 600            # seconds without a finished request before an attempt is restarted
POLL = 30
MAX_ATTEMPTS = 300
# Not a bare "403": an expired S3 part URL also answers 403, and that is retryable.
FATAL = re.compile(r"storage limit reached|401 Unauthorized")

status: dict = {"started": time.strftime("%F %T"), "jobs": {}}


def parts_done(job: dict) -> tuple[int, int, int, str]:
    """(requests, bytes, retries, last retry) of this attempt, from the uploader's --progress file."""
    path = LOGS / f"{job['name']}.parts"
    n = total = retries = 0
    last_retry = ""
    if path.exists():
        for line in path.read_text().splitlines():
            fields = line.split()
            if len(fields) > 2 and fields[2] == "PUT":
                n += 1
                if len(fields) > 4 and fields[4].isdigit():
                    total += int(fields[4])
            elif len(fields) > 2 and fields[2] == "RETRY":
                if "thrown while" in line or "HTTP Error" in line:
                    retries += 1
                    last_retry = line
    return n, total, retries, last_retry


def save_status() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    status["updated"] = time.strftime("%F %T")
    (LOGS / "status.json").write_text(json.dumps(status, indent=1, ensure_ascii=False))
    lines = [f"# HF 上传状态（更新于 {status['updated']}）", "",
             f"驱动启动于 {status['started']}。驱动日志：`journalctl --user -u materiaviva-hf-upload`；"
             f"每个任务的上传输出在 `data/hf-release-logs/<任务>.log`。", ""]
    for job in JOBS:
        s = status["jobs"].get(job["name"], {"state": "等待"})
        scope = (f"（只传 {', '.join(job['include'])}）" if job.get("include") else
                 f"（不含 {', '.join(job['exclude'])}）" if job.get("exclude") else "")
        lines.append(f"## {job['name']} → {job['repo']}{scope}")
        lines.append(f"- 状态：**{s['state']}**")
        n, total, retries, last_retry = parts_done(job)
        if n:
            lines.append(f"- 本次尝试已完成上传请求：{n} 个，{total / 1e9:.2f} GB（大文件按 23 MB 分块计）")
        if retries:
            lines.append(f"- 本次尝试网络重试：{retries} 次（进程内重试，已传分块不丢）；最近一次：`{last_retry[:160]}`")
        for key, label in (("attempts", "尝试次数"), ("restarts_on_stall", "卡住后重启"),
                           ("upload_started", "开始"), ("upload_finished", "上传结束"),
                           ("progress", "最近进度"), ("error", "错误")):
            if s.get(key) not in (None, ""):
                lines.append(f"- {label}：{s[key]}")
        v = s.get("verify")
        if v:
            lines.append(f"- 校验：{'通过' if v['ok'] else '**未通过**'}，{v['files']} 个文件逐个比对"
                         f"大小和哈希（LFS 比 sha256，普通文件比 git blob）")
            for p in v["problems"][:20]:
                lines.append(f"  - {p}")
            if v["n_remote_only"]:
                lines.append(f"  - HF 上另有 {v['n_remote_only']} 个本地目录里没有的文件（未动）："
                             f"{', '.join(v['remote_only'][:8])}{' …' if v['n_remote_only'] > 8 else ''}")
        lines.append("")
    if status.get("finished"):
        lines.append(f"全部结束于 {status['finished']}。")
    (LOGS / "STATUS.md").write_text("\n".join(lines))


def log(msg: str) -> None:
    print(f"[{time.strftime('%F %T')}] {msg}", flush=True)


def notify(msg: str) -> None:
    """Desktop notification, so the outcome reaches the user without any session open."""
    log(msg)
    try:
        subprocess.run(["notify-send", "-a", "MateriaViva", "-t", "0", "HF 上传", msg], timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def last_files_line(path: Path) -> str:
    with path.open("rb") as fh:
        fh.seek(max(0, path.stat().st_size - 4000))
        tail = fh.read().decode("utf-8", "replace")
    hits = re.findall(r"Files:[^\n]*", tail)
    return hits[-1].strip() if hits else ""


def kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=20)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def upload(job: dict) -> bool:
    s = status["jobs"].setdefault(job["name"], {})
    s.update(state="上传中", attempts=0, restarts_on_stall=0, upload_started=time.strftime("%F %T"))
    save_status()
    cli_log = LOGS / f"{job['name']}.log"
    parts = LOGS / f"{job['name']}.parts"
    cmd = [sys.executable, str(UPLOADER), job["repo"], job["folder"], "--repo-type", "dataset",
           "--num-workers", "2", "--progress", str(parts)]
    for pattern in job.get("include", []):
        cmd += ["--include", pattern]
    for pattern in job.get("exclude", []):
        cmd += ["--exclude", pattern]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        s["attempts"] = attempt
        parts.write_text("")       # an interrupted multipart upload starts over, so count per attempt
        save_status()
        start = cli_log.stat().st_size if cli_log.exists() else 0
        with cli_log.open("ab") as out:
            out.write(f"\n=== attempt {attempt} {time.strftime('%F %T')}\n".encode())
            out.flush()
            proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        log(f"{job['name']}: attempt {attempt}, pid {proc.pid}")
        marker, last_progress = None, time.time()
        while proc.poll() is None:
            time.sleep(POLL)
            line = last_files_line(cli_log) if cli_log.exists() else ""
            now = (line, parts.stat().st_mtime if parts.exists() else 0)
            if now != marker:
                marker, last_progress = now, time.time()
                if line:
                    s["progress"] = line.removeprefix("Files:").strip()
                save_status()
            with cli_log.open("rb") as fh:
                fh.seek(start)
                fatal = FATAL.search(fh.read().decode("utf-8", "replace"))
            if fatal:
                kill(proc)
                s.update(state="失败（不重试）", error=fatal.group(0))
                save_status()
                log(f"{job['name']}: fatal {fatal.group(0)}")
                return False
            if time.time() - last_progress > STALL:
                log(f"{job['name']}: no progress for {STALL}s, restarting")
                s["restarts_on_stall"] += 1
                kill(proc)
                break
        if proc.returncode == 0:
            s.update(state="上传完成，校验中", upload_finished=time.strftime("%F %T"))
            save_status()
            return True
        time.sleep(20)
    s.update(state="失败（尝试次数用尽）")
    save_status()
    return False


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def cached_sha256(folder: Path, rel: str, path: Path) -> str:
    """The sha256 ``upload-large-folder`` stored while hashing, if still current."""
    meta = folder / ".cache" / "huggingface" / "upload" / f"{rel}.metadata"
    try:
        stamp, size, _, digest = meta.read_text().splitlines()[:4]
        st = path.stat()
        if int(size) == st.st_size and float(stamp) >= st.st_mtime and len(digest) == 64:
            return digest
    except (OSError, ValueError):
        pass
    return sha256(path)


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def in_scope(job: dict, rel: str) -> bool:
    """Same pattern semantics as upload_large_folder's allow/ignore patterns (fnmatch)."""
    if job.get("include") and not any(fnmatch.fnmatch(rel, p) for p in job["include"]):
        return False
    return not any(fnmatch.fnmatch(rel, p) for p in job.get("exclude", []))


def verify(job: dict) -> dict:
    folder = PROJECT_ROOT / job["folder"]
    remote = {f.path: f for f in HfApi().list_repo_tree(job["repo"], repo_type="dataset", recursive=True)
              if isinstance(f, RepoFile)}
    local = {p.relative_to(folder).as_posix(): p for p in folder.rglob("*")
             if p.is_file() and ".cache" not in p.relative_to(folder).parts}
    problems = []
    checked = 0
    for rel, p in sorted(local.items()):
        if not in_scope(job, rel):
            continue
        checked += 1
        r = remote.get(rel)
        if r is None:
            problems.append(f"HF 上缺少 {rel}")
        elif r.size != p.stat().st_size:
            problems.append(f"{rel} 大小不符：HF {r.size}，本地 {p.stat().st_size}")
        elif r.lfs is not None and r.lfs.sha256 != cached_sha256(folder, rel, p):
            problems.append(f"{rel} sha256 不符")
        elif r.lfs is None and r.blob_id != git_blob_sha1(p):
            problems.append(f"{rel} 内容不符")
    remote_only = sorted(set(remote) - set(local) - {".gitattributes"})
    return {"ok": not problems, "files": checked, "problems": problems,
            "n_remote_only": len(remote_only), "remote_only": remote_only[:50]}


def main() -> int:
    for job in JOBS:
        if not upload(job):
            state = status["jobs"][job["name"]]["state"]
            notify(f"{job['name']} 失败：{state} {status['jobs'][job['name']].get('error', '')}，"
                   f"详情见 data/hf-release-logs/STATUS.md")
            if state.startswith("失败（不重试）"):
                return 0           # permanent; a systemd restart would only repeat it
            return 1
        for _ in range(5):
            try:
                v = verify(job)
                break
            except Exception as exc:  # network blip on the listing
                log(f"{job['name']}: verify failed ({exc}), retrying")
                time.sleep(60)
        else:
            status["jobs"][job["name"]].update(state="上传完成，校验出错")
            save_status()
            return 1
        status["jobs"][job["name"]].update(verify=v, state="完成，校验通过" if v["ok"] else "完成，校验未通过")
        save_status()
        log(f"{job['name']}: verify ok={v['ok']} files={v['files']} problems={len(v['problems'])}")
    status["finished"] = time.strftime("%F %T")
    save_status()
    bad = [j["name"] for j in JOBS if not status["jobs"][j["name"]]["verify"]["ok"]]
    if bad:
        notify(f"上传结束，但校验未通过：{', '.join(bad)}；见 data/hf-release-logs/STATUS.md")
        return 0
    (LOGS / "DONE").write_text(status["finished"] + "\n")   # the boot-time unit skips itself after this
    notify("两个版本都已上传并逐文件校验通过（AI4QC/MateriaViva、AI4QC/MateriaViva-Open）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
