## Submission Checklist

Before opening this PR, confirm the following:

- [ ] `proxy/Dockerfile` exists and builds cleanly
- [ ] `docker compose up --build` starts without errors
- [ ] `GET /health` returns 200
- [ ] `GET /metrics` exposes all required instrumentation metrics
- [ ] Local benchmark run committed to `results/`
- [ ] `DESIGN.md` fully filled in (no placeholder text remaining)

---

## Classification

**Algorithm** *(how do you infer frequency tier from raw sample stream?)*:

**Cold-start strategy** *(what happens in the first N seconds before you have history?)*:

**Convergence window** *(how long until confident? why that window?)*:

**Reclassification** *(what if a series changes frequency mid-run?)*:

---

## Per-Tier Batching

**Alpha tier** — flush interval / max batch / compression / reasoning:

**Beta tier** — flush interval / max batch / compression / reasoning:

**Gamma tier** — flush interval / max batch / compression / reasoning:

**Why not uniform?** *(what breaks with a single config across all tiers?)*:

---

## Durability

**Guarantee** *(at-least-once / at-most-once / exactly-once — be precise)*:

**Buffer implementation** *(in-memory / disk / both, size limit, format)*:

**Restart recovery** *(what happens to buffered data across a proxy restart?)*:

**Backend failure handling** *(503 / 429 / 400 / slow response — each one)*:

---

## Degradation Policy

**Trigger** *(at what threshold does degradation begin and how is it detected?)*:

**Shed order** *(what gets dropped first and why?)*:

**Recovery** *(how does the proxy return to normal operation?)*:

---

## Self-Instrumentation

*For each metric: what question does it answer for an on-call engineer at 3am?*

| Metric | Answers the question... |
|--------|------------------------|
| `proxy_samples_received_total` | |
| `proxy_samples_forwarded_total` | |
| `proxy_samples_dropped_total` | |
| `proxy_buffer_bytes` | |
| `proxy_backend_requests_total` | |

---

## Local Benchmark Results

*Paste the fidelity output from your local run:*

```
alpha  (   1 Hz)  expected=...  observed=...  fidelity=...%
beta   ( 100 Hz)  expected=...  observed=...  fidelity=...%
gamma  ( 500 Hz)  expected=...  observed=...  fidelity=...%
```

---

## One Thing You'd Change at 10x Load

*(One concrete architectural change if this handled 10x the current series count)*:
