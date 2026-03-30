# Origin DevOps Assignment — Telemetry Proxy

## The Problem

A fleet of sensors emits telemetry at three different frequencies — some fire once per second, others at 100 Hz or 500 Hz. All data flows through the same push pipeline.

Your job is to build a **telemetry proxy** that sits between the sensor data generator and a VictoriaMetrics backend. The proxy must:

- Accept incoming metric data on `POST /push` (Prometheus text format)
- Classify each series by its frequency tier, **by observing sample rate** — no frequency label is provided
- Apply an appropriate forwarding strategy per tier (batching, compression, flush interval)
- Buffer durably to disk so data survives a proxy restart
- Forward to the backend at `BACKEND_URL/api/v1/import/prometheus`
- Stay within a **hard 150 MiB RSS limit** enforced by the container runtime
- Degrade gracefully when under memory pressure
- Expose `GET /health` (200 when ready) and `GET /metrics` (Prometheus text format, self-instrumentation)

## What You Are Given

| Path | Description |
|------|-------------|
| `generator/` | Sensor data generator — **do not modify** |
| `harness/run_benchmark.py` | Visible benchmark — run this to test locally |
| `docker-compose.yml` | Wires generator → proxy → VictoriaMetrics |
| `DESIGN.md` | Document you must fill in and submit |
| `proxy/` | Empty — your implementation goes here |

## Proxy Interface Contract

```
POST /push
  Content-Type: text/plain
  Body: Prometheus text format (one sample per line)
  Response: 204 on success, 4xx on bad input, 503 if temporarily unavailable

GET /health
  Response: 200 {"status":"ok"} when proxy is ready to accept data

GET /metrics
  Response: Prometheus text format — self-instrumentation metrics
```

### Required Self-Instrumentation Metrics

Your proxy **must** expose these metrics on `GET /metrics`. The harness checks for them:

```
proxy_samples_received_total{tier="..."}
proxy_samples_forwarded_total{tier="..."}
proxy_samples_dropped_total{tier="...", reason="..."}
proxy_buffer_bytes{location="memory|disk"}
proxy_backend_requests_total{status="2xx|429|503|timeout|error"}
```

## Running Locally

```bash
# Build and start the full stack
docker compose up --build

# In a separate terminal, run the benchmark (default: 600s)
cd harness
python run_benchmark.py

# Results are written to results/<run_id>/summary.json
```

The benchmark runs for 10 minutes and prints fidelity per sensor class at the end.

## Submission

1. Fork this repository
2. Implement your proxy in `proxy/` — any language, must ship as a Docker image
3. Fill in `DESIGN.md` completely — this is reviewed by a human and counts for 35% of your score
4. Commit a local benchmark run to `results/` so reviewers can see your baseline
5. Open a pull request against this repository

CI will run automatically on your PR and post a score as a comment.

## Scoring

| Component | Weight | How |
|-----------|--------|-----|
| Fidelity — visible benchmark | 10% | Automated: your local run results |
| Fidelity — hidden scenarios | 40% | Automated: unknown load patterns, failure injections |
| Self-instrumentation correctness | 15% | Automated: harness checks required metrics are present and accurate |
| `DESIGN.md` quality | 35% | Human review |

Hidden scenarios probe things the visible benchmark does not test. You will see your total hidden score (e.g. "5/8 scenarios passed") but not which scenarios ran or what they tested.

## Constraints

- Proxy memory: hard 150 MiB RSS (`mem_limit` in docker-compose, enforced by the harness)
- Do not modify `generator/`, `harness/`, or `docker-compose.yml` except the `proxy` service section
- The generator pushes to `http://proxy:8080/push` — your proxy must listen on port 8080
- Backend is always `http://victoriametrics:8428` in the composed environment

## Notes on Classification

The metric stream provides **no explicit frequency labels**. The metric names do not encode frequency. Your proxy must infer tier by observing how frequently each series delivers samples.

Do not try to reverse-engineer tier from metric names or series IDs — the hidden test scenarios use different metric names than the visible benchmark.

## Time Expectation

This is a weekend assignment (~2 days). A working implementation that passes the visible benchmark is a baseline. What separates candidates is the robustness under hidden scenarios and the quality of the DESIGN.md.
