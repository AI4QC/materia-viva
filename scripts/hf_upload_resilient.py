#!/usr/bin/env python3
"""`hf upload-large-folder` that survives the lab proxy.

Measured through the local Clash/mihomo TUN proxy (2026-10-22/23), uplink ~1.5 MB/s:

* the proxy ACKs data locally and drops long connections. huggingface_hub builds its
  httpx client with ``timeout=None``, so a dropped request waits forever (2026-10-20:
  2.5 days with no error);
* Xet pre-uploads up to 256 files in one session and an unfinished session is not
  reused on restart (the same parquet was re-sent in full by three attempts). A 23 GB
  file is one session -- about 4 h without a drop, which never happens here.

So by default this uploads through classic LFS, which the Hub still accepts on Xet
repos: one file per batch, multipart parts sent with read/write timeouts and patient
retries, so a dropped connection costs one part instead of the file. Every finished
PUT, and every retry, is appended to ``--progress`` for the supervisor
(``hf_release_upload.py``), so it can tell a retrying upload from a hung one.
``--transport xet --batch 1`` keeps Xet, one file per session.

A multipart upload cannot be resumed by a new process (each batch request opens a new
one), so everything here keeps the process alive through an outage. Found 2026-10-23,
when one failed TLS handshake at 02:00 threw away 10.4 GB of finished parts and the
network then stayed down until 03:39: huggingface_hub 1.7.1 closes the shared client on
``ConnectError`` but goes on retrying with it, and the next try raises "client has been
closed" (a RuntimeError, never retried).

    python scripts/hf_upload_resilient.py AI4QC/MateriaViva data/hf-upload \\
        --include index/materials.sqlite --progress data/hf-release-logs/full-sqlite.parts
"""

from __future__ import annotations

import argparse
import logging
import os
import time
import urllib.parse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo_id")
    ap.add_argument("folder")
    ap.add_argument("--repo-type", default="dataset")
    ap.add_argument("--include", action="append")
    ap.add_argument("--exclude", action="append")
    ap.add_argument("--num-workers", type=int, default=2)
    ap.add_argument("--transport", choices=("lfs", "xet"), default="lfs")
    ap.add_argument("--batch", type=int, default=1, help="files per Xet session (xet only)")
    ap.add_argument("--progress", type=Path, help="append one line per finished upload request")
    args = ap.parse_args()

    if args.transport == "lfs":
        os.environ["HF_HUB_DISABLE_XET"] = "1"      # read once, when huggingface_hub is imported
    import httpx
    import huggingface_hub
    import huggingface_hub._upload_large_folder as ulf
    import huggingface_hub.lfs as lfs
    from huggingface_hub.utils import _http

    huggingface_hub.set_client_factory(lambda: httpx.Client(
        event_hooks={"request": [_http.hf_request_event_hook]}, follow_redirects=True,
        timeout=httpx.Timeout(connect=60, read=300, write=300, pool=60)))

    def drop_session():
        # New calls build a fresh client; the one a retry loop holds stays open.
        _http._GLOBAL_CLIENT = None

    _http.close_session = drop_session               # _http_backoff_base looks it up at call time

    def note(text: str) -> None:
        if args.progress:
            with args.progress.open("a") as fh:
                fh.write(f"{time.strftime('%F %T')} {text}\n")

    class Heartbeat(logging.Handler):
        def emit(self, record):
            note(f"RETRY {record.getMessage()[:300]}")

    logging.getLogger("huggingface_hub.utils._http").addHandler(Heartbeat(logging.WARNING))

    backoff = lfs.http_backoff
    signed = []

    def patient_backoff(method, url, **kwargs):
        # ~10 h of retries at 60 s: outlasts the 1.6 h outage of 2026-10-23. An expired part
        # URL answers 403, which is not retried, so the file then starts a new multipart.
        kwargs.setdefault("retry_on_exceptions",
                          (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))
        if method == "PUT":                          # S3 RequestTimeout is a 400
            kwargs.setdefault("retry_on_status_codes", (400, 408, 429, 500, 502, 503, 504))
            if not signed:
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                if "X-Amz-Expires" in q:
                    signed.append(1)
                    note(f"INFO part URLs signed {q.get('X-Amz-Date', ['?'])[0]}, "
                         f"valid {q['X-Amz-Expires'][0]} s")
        t0 = time.time()
        resp = backoff(method, url, max_retries=600, base_wait_time=5, max_wait_time=60, **kwargs)
        if method == "PUT":
            size = getattr(kwargs.get("data"), "_len", None)     # SliceFileObj = one part
            note(f"PUT {resp.status_code} {size or '-'} B {time.time() - t0:.0f}s")
        return resp

    lfs.http_backoff = patient_backoff               # lfs.py looks it up at call time
    ulf.UPLOAD_BATCH_SIZE_XET = args.batch

    huggingface_hub.HfApi().upload_large_folder(
        repo_id=args.repo_id, folder_path=args.folder, repo_type=args.repo_type,
        allow_patterns=args.include, ignore_patterns=args.exclude,
        num_workers=args.num_workers, print_report_every=60,
    )


if __name__ == "__main__":
    main()
