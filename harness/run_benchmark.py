"""
Benchmark harness for the Origin DevOps assignment.

Runs the full stack, measures fidelity per sensor class, checks proxy
self-instrumentation, and writes a summary.json to results/<run_id>/.

Candidates must NOT modify this file.
"""

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"

DURATION_SEC = int(os.environ.get("BENCHMARK_DURATION_SEC", "600"))
RUN_ID = os.environ.get("RUN_ID", f"bench-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
POLL_INTERVAL_SEC = float(os.environ.get("RESOURCE_POLL_INTERVAL_SEC", "2"))

VM_URL = os.environ.get("VM_URL", "http://127.0.0.1:8428")
PROXY_URL = os.environ.get("PROXY_URL", "http://127.0.0.1:8080")
GENERATOR_STATUS_URL = os.environ.get("GENERATOR_STATUS_URL", "http://127.0.0.1:8000")

DRAIN_TIMEOUT_SEC = int(os.environ.get("DRAIN_TIMEOUT_SEC", "90"))
DRAIN_POLL_SEC = float(os.environ.get("DRAIN_POLL_SEC", "2"))

# Internal mapping: which metric name corresponds to which sensor class.
# This is not exposed to the proxy — it must classify by sample rate.
CLASS_MAP = {
    "alpha": {
        "metric": "origin_telemetry_alpha_push",
        "hz": 1,
        "count": int(os.environ.get("COUNT_ALPHA", "1120")),
    },
    "beta": {
        "metric": "origin_telemetry_beta_push",
        "hz": 100,
        "count": int(os.environ.get("COUNT_BETA", "120")),
    },
    "gamma": {
        "metric": "origin_telemetry_gamma_push",
        "hz": 500,
        "count": int(os.environ.get("COUNT_GAMMA", "20")),
    },
}

# Proxy self-instrumentation: metrics the proxy MUST expose correctly.
REQUIRED_PROXY_METRICS = [
    "proxy_samples_received_total",
    "proxy_samples_forwarded_total",
    "proxy_samples_dropped_total",
    "proxy_buffer_bytes",
    "proxy_backend_requests_total",
]

stop_monitor = threading.Event()


def run_cmd(args, check=True, capture_output=True):
    return subprocess.run(
        args, cwd=ROOT, check=check, text=True, capture_output=capture_output
    )


def http_get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode()


def http_get_json(url, timeout=10):
    return json.loads(http_get(url, timeout=timeout))


def wait_for_http(url, timeout_sec=120, label=""):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if 200 <= resp.status < 500:
                    return
        except Exception:
            time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {label or url}")


def query_vm(expr, window_sec):
    url = (
        f"{VM_URL}/api/v1/query?"
        + urllib.parse.urlencode({"query": expr, "time": str(int(time.time()))})
    )
    data = http_get_json(url)
    if data.get("status") != "success":
        return 0.0
    result = data["data"]["result"]
    if not result:
        return 0.0
    return float(result[0]["value"][1])


def count_samples_in_vm(metric_name, run_id, window_sec):
    expr = f'sum(count_over_time({metric_name}{{run_id="{run_id}"}}[{window_sec}s]))'
    return query_vm(expr, window_sec)


def check_proxy_instrumentation():
    """Scrape proxy /metrics and verify required metrics are present."""
    try:
        body = http_get(f"{PROXY_URL}/metrics", timeout=5)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "missing": REQUIRED_PROXY_METRICS}

    present = []
    missing = []
    for metric in REQUIRED_PROXY_METRICS:
        if metric in body:
            present.append(metric)
        else:
            missing.append(metric)

    return {
        "ok": len(missing) == 0,
        "present": present,
        "missing": missing,
    }


def parse_size_to_mib(text):
    text = text.strip()
    match = re.match(r"([0-9.]+)\s*([KMG]i?B|B)", text)
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2)
    factors = {"B": 1 / (1024**2), "KiB": 1 / 1024, "MiB": 1, "GiB": 1024,
               "KB": 1 / 1024, "MB": 1, "GB": 1024}
    return value * factors.get(unit, 0)


def parse_net_to_bytes(text):
    match = re.match(r"([0-9.]+)\s*([KMG]i?B|[kMG]?B)", text.strip())
    if not match:
        return 0
    value, unit = float(match.group(1)), match.group(2)
    factors = {"B": 1, "kB": 1000, "MB": 1000**2, "GB": 1000**3,
               "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    return int(value * factors.get(unit, 1))


def collect_container_stats(names):
    result = run_cmd(["docker", "stats", "--no-stream", "--format", "{{json .}}", *names])
    entries = []
    for line in result.stdout.splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def monitor_resources(results):
    container_samples = {
        name: {"cpu": [], "mem_mib": []}
        for name in ["proxy", "victoriametrics", "generator"]
    }

    while not stop_monitor.wait(POLL_INTERVAL_SEC):
        try:
            for item in collect_container_stats(["proxy", "victoriametrics", "generator"]):
                name = item["Name"]
                if name not in container_samples:
                    continue
                mem_str = item["MemUsage"].split("/")[0].strip()
                container_samples[name]["cpu"].append(
                    float(item["CPUPerc"].rstrip("%"))
                )
                container_samples[name]["mem_mib"].append(parse_size_to_mib(mem_str))
        except Exception:
            pass

    def summarise(samples):
        if not samples:
            return {"avg": 0.0, "max": 0.0}
        return {"avg": round(sum(samples) / len(samples), 3), "max": round(max(samples), 3)}

    results["resources"] = {
        name: {
            "cpu_percent": summarise(series["cpu"]),
            "mem_mib": summarise(series["mem_mib"]),
        }
        for name, series in container_samples.items()
    }


def wait_for_drain(run_id, duration_sec):
    window = duration_sec + DRAIN_TIMEOUT_SEC + 60
    deadline = time.time() + DRAIN_TIMEOUT_SEC
    last_counts = None
    stable = 0
    history = []

    while time.time() < deadline:
        counts = {
            class_name: int(round(count_samples_in_vm(cfg["metric"], run_id, window)))
            for class_name, cfg in CLASS_MAP.items()
        }
        history.append({
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "counts": counts,
        })
        if counts == last_counts:
            stable += 1
            if stable >= 2:
                return {"final_counts": counts, "history": history, "timed_out": False}
        else:
            stable = 0
        last_counts = counts
        time.sleep(DRAIN_POLL_SEC)

    return {"final_counts": last_counts or {}, "history": history, "timed_out": True}


def build_fidelity(generator_status, duration_sec, drain_counts):
    window = duration_sec + DRAIN_TIMEOUT_SEC + 60
    summary = {}
    for class_name, cfg in CLASS_MAP.items():
        expected = generator_status["per_class"][class_name]["samples_generated"]
        observed = drain_counts.get(class_name, 0)
        ratio = round(observed / expected, 6) if expected else 0.0
        summary[class_name] = {
            "hz": cfg["hz"],
            "series_count": cfg["count"],
            "expected_samples": expected,
            "observed_samples": observed,
            "fidelity_ratio": ratio,
        }
    return summary


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    if sys.platform != "linux":
        print("Warning: this harness is designed for Linux hosts.")

    results = {
        "run_id": RUN_ID,
        "duration_sec": DURATION_SEC,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    run_dir = RESULTS_DIR / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[harness] starting stack run_id={RUN_ID}")
    run_cmd(["docker", "compose", "up", "-d", "--build", "victoriametrics", "proxy"])
    wait_for_http(f"{VM_URL}/health", label="victoriametrics")
    wait_for_http(f"{PROXY_URL}/health", label="proxy")

    print("[harness] stack healthy, starting generator")
    run_cmd(["docker", "compose", "up", "-d", "generator"])
    wait_for_http(f"{GENERATOR_STATUS_URL}/status", label="generator")

    monitor_results = {}
    monitor_thread = threading.Thread(
        target=monitor_resources, args=(monitor_results,), daemon=True
    )
    monitor_thread.start()

    try:
        print(f"[harness] running for {DURATION_SEC}s ...")
        time.sleep(DURATION_SEC)
        generator_status = http_get_json(f"{GENERATOR_STATUS_URL}/status")
    finally:
        stop_monitor.set()
        monitor_thread.join(timeout=10)
        run_cmd(["docker", "compose", "stop", "generator"], check=False)

    print("[harness] waiting for proxy to drain buffer ...")
    drain = wait_for_drain(RUN_ID, DURATION_SEC)

    print("[harness] checking proxy self-instrumentation ...")
    instrumentation = check_proxy_instrumentation()

    fidelity = build_fidelity(generator_status, DURATION_SEC, drain["final_counts"])

    results.update({
        "generator_status": generator_status,
        "drain": drain,
        "fidelity": fidelity,
        "proxy_instrumentation": instrumentation,
        "resources": monitor_results.get("resources", {}),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    })

    out_path = run_dir / "summary.json"
    write_json(out_path, results)

    print("\n=== FIDELITY RESULTS ===")
    for class_name, data in fidelity.items():
        ratio_pct = data["fidelity_ratio"] * 100
        print(
            f"  {class_name:6s} ({data['hz']:>4d} Hz) "
            f"expected={data['expected_samples']:>10,d} "
            f"observed={data['observed_samples']:>10,d} "
            f"fidelity={ratio_pct:.2f}%"
        )

    print("\n=== PROXY INSTRUMENTATION ===")
    if instrumentation["ok"]:
        print("  all required metrics present")
    else:
        print(f"  MISSING: {instrumentation['missing']}")

    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
