"""
Telemetry generator for the Origin DevOps assignment.

Emits three classes of sensor data at different frequencies over a push pipeline.
Candidates must NOT modify this file.
"""

import json
import logging
import math
import os
import signal
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True)
class SensorClass:
    name: str
    hz: int
    count: int
    metric_name: str


RUN_ID = os.environ.get("RUN_ID", f"run-{int(time.time())}")
PROXY_URL = os.environ.get("PROXY_URL", "http://127.0.0.1:8080")
LOG_PATH = os.environ.get("LOG_PATH", "logs/generator.log")
METRICS_HOST = os.environ.get("METRICS_HOST", "0.0.0.0")
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8000"))
PUSH_BATCH_INTERVAL_SEC = float(os.environ.get("PUSH_BATCH_INTERVAL_SEC", "0.2"))
BENCHMARK_DURATION_SEC = float(os.environ.get("BENCHMARK_DURATION_SEC", "0"))
LOG_EVERY_SEC = float(os.environ.get("LOG_EVERY_SEC", "5"))

# Three sensor classes at different frequencies.
# Metric names are intentionally opaque — the proxy must classify by observed
# sample rate, not by metric name.
CLASSES = [
    SensorClass(
        "alpha",
        1,
        int(os.environ.get("COUNT_ALPHA", "1120")),
        "origin_telemetry_alpha_push",
    ),
    SensorClass(
        "beta",
        100,
        int(os.environ.get("COUNT_BETA", "120")),
        "origin_telemetry_beta_push",
    ),
    SensorClass(
        "gamma",
        500,
        int(os.environ.get("COUNT_GAMMA", "20")),
        "origin_telemetry_gamma_push",
    ),
]

os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

STOP_EVENT = threading.Event()
START_TIME = time.time()

STATS = {
    "run_id": RUN_ID,
    "start_unix_ms": int(START_TIME * 1000),
    "push_batches_sent": 0,
    "push_batches_failed": 0,
    "push_payload_bytes_sent": 0,
    "metrics_scrape_requests": 0,
    "metrics_scrape_bytes": 0,
    "per_class": {
        sc.name: {
            "hz": sc.hz,
            "series_count": sc.count,
            "samples_generated": 0,
        }
        for sc in CLASSES
    },
}
STATS_LOCK = threading.Lock()
BUFFER = []
BUFFER_LOCK = threading.Lock()


def update_value(class_name: str, series_idx: int, sample_index: int, hz: int) -> float:
    base = series_idx * 0.125
    return (
        base
        + math.sin((sample_index / hz) + (series_idx * 0.01)) * 10.0
        + math.cos((sample_index / max(hz, 1)) * 0.3 + (series_idx * 0.005)) * 2.0
    )


def build_push_line(metric_name: str, series_id: str, value: float, ts_ms: int) -> str:
    return (
        f'{metric_name}{{run_id="{RUN_ID}",series_id="{series_id}"}} '
        f"{value:.6f} {ts_ms}"
    )


def flush_buffer_once() -> bool:
    target_url = f"{PROXY_URL.rstrip('/')}/push"
    with BUFFER_LOCK:
        if not BUFFER:
            return True
        payload_lines = list(BUFFER)
        BUFFER.clear()
    payload = "\n".join(payload_lines).encode()
    try:
        req = urllib.request.Request(target_url, data=payload, method="POST")
        req.add_header("Content-Type", "text/plain")
        with urllib.request.urlopen(req, timeout=5):
            pass
        with STATS_LOCK:
            STATS["push_batches_sent"] += 1
            STATS["push_payload_bytes_sent"] += len(payload)
        return True
    except urllib.error.URLError as exc:
        with BUFFER_LOCK:
            BUFFER[:0] = payload_lines
        with STATS_LOCK:
            STATS["push_batches_failed"] += 1
        log.warning("proxy push failed: %s", exc)
        return False


def push_worker() -> None:
    while not STOP_EVENT.is_set():
        STOP_EVENT.wait(PUSH_BATCH_INTERVAL_SEC)
        flush_buffer_once()


def class_worker(sc: SensorClass) -> None:
    next_tick = time.perf_counter()
    sample_index = 0

    while not STOP_EVENT.is_set():
        next_tick += 1.0 / sc.hz
        remaining = next_tick - time.perf_counter()
        if remaining > 0:
            STOP_EVENT.wait(remaining)
        if STOP_EVENT.is_set():
            break

        ts_ms = int(time.time() * 1000)
        batch_lines = []
        for idx in range(sc.count):
            series_id = f"{idx:04d}"
            value = update_value(sc.name, idx, sample_index, sc.hz)
            batch_lines.append(build_push_line(sc.metric_name, series_id, value, ts_ms))

        with BUFFER_LOCK:
            BUFFER.extend(batch_lines)
        with STATS_LOCK:
            STATS["per_class"][sc.name]["samples_generated"] += sc.count
        sample_index += 1


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/status":
            with BUFFER_LOCK:
                buffered_lines = len(BUFFER)
            with STATS_LOCK:
                status_payload = dict(STATS)
                status_payload["uptime_sec"] = time.time() - START_TIME
                status_payload["buffered_lines"] = buffered_lines
            body = json.dumps(status_payload, indent=2, sort_keys=True).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format_str: str, *args) -> None:
        log.info("http %s", format_str % args)


def status_logger() -> None:
    while not STOP_EVENT.wait(LOG_EVERY_SEC):
        with STATS_LOCK:
            parts = []
            for class_name, class_stats in STATS["per_class"].items():
                parts.append(
                    f"{class_name}:series={class_stats['series_count']} "
                    f"samples={class_stats['samples_generated']}"
                )
            log.info(
                "run_id=%s push_batches=%s failed=%s payload_bytes=%s %s",
                RUN_ID,
                STATS["push_batches_sent"],
                STATS["push_batches_failed"],
                STATS["push_payload_bytes_sent"],
                " | ".join(parts),
            )


def serve() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((METRICS_HOST, METRICS_PORT), StatusHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def request_stop(*_args) -> None:
    STOP_EVENT.set()


def flush_remaining_buffer() -> None:
    for _ in range(10):
        with BUFFER_LOCK:
            if not BUFFER:
                return
        if flush_buffer_once():
            continue
        time.sleep(min(PUSH_BATCH_INTERVAL_SEC, 1.0))
    with BUFFER_LOCK:
        remaining = len(BUFFER)
    log.warning("generator exiting with %s buffered samples still pending", remaining)


def main() -> None:
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    server = serve()
    log.info(
        "generator started run_id=%s proxy=%s",
        RUN_ID,
        PROXY_URL,
    )
    for sc in CLASSES:
        log.info("class=%s hz=%s series=%s metric=%s", sc.name, sc.hz, sc.count, sc.metric_name)

    threads = [
        threading.Thread(target=push_worker, daemon=True),
        threading.Thread(target=status_logger, daemon=True),
    ]
    threads.extend(
        threading.Thread(target=class_worker, args=(sc,), daemon=True) for sc in CLASSES
    )
    for thread in threads:
        thread.start()

    if BENCHMARK_DURATION_SEC > 0:
        STOP_EVENT.wait(BENCHMARK_DURATION_SEC)
        STOP_EVENT.set()
    else:
        STOP_EVENT.wait()

    flush_remaining_buffer()
    server.shutdown()
    server.server_close()
    log.info("generator stopped run_id=%s", RUN_ID)


if __name__ == "__main__":
    main()
