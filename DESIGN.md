# Proxy Design Document

> Fill this in before submitting your PR. This document is reviewed by a human and
> counts for 35% of your total score. Generic answers score poorly — be specific
> about your numbers, your trade-offs, and your reasoning.

---

## 1. Classification

**Algorithm:**
<!-- How does your proxy determine the frequency tier of an incoming series?
     Be specific: what signal do you observe, over what window, and how do you
     make the classification decision? -->

**Cold-start strategy:**
<!-- What happens in the first N seconds before you have enough history to
     classify? What do you do with those samples, and what does that cost? -->

**Convergence window:**
<!-- How long until you're confident in a classification? Why that window and not
     shorter or longer? What's the accuracy/latency trade-off you accepted? -->

**Reclassification:**
<!-- What happens if a series changes frequency mid-run (e.g. a sensor goes from
     1 Hz standby to 100 Hz active)? How does your proxy detect and handle it? -->

---

## 2. Per-Tier Batching Strategy

> For each tier, state the specific values you chose and why.

**Alpha tier (expected ~1 Hz):**
- Flush interval: `___ s`
- Max batch size: `___ samples` / `___ bytes`
- Compression: ___
- Reasoning:

**Beta tier (expected ~100 Hz):**
- Flush interval: `___ s`
- Max batch size: `___ samples` / `___ bytes`
- Compression: ___
- Reasoning:

**Gamma tier (expected ~500 Hz):**
- Flush interval: `___ s`
- Max batch size: `___ samples` / `___ bytes`
- Compression: ___
- Reasoning:

**Why not uniform across all tiers?**
<!-- What breaks if you use the same batching config for all tiers? -->

---

## 3. Durability Model

**What is guaranteed:**
<!-- At-least-once? At-most-once? Exactly-once? Be precise. -->

**Buffer implementation:**
<!-- In-memory, disk, or both? Where is the buffer on disk (path, format)?
     What is its size limit and how is that limit enforced? -->

**Restart recovery:**
<!-- If the proxy crashes at T=300s and restarts at T=305s, what happens to
     samples buffered between T=0 and T=300? Walk through the exact steps. -->

**Partial backend success:**
<!-- VictoriaMetrics can accept some samples and reject others in a single
     request. How does your proxy handle this? What gets retried, what gets
     committed as forwarded? -->

**Backend failure modes:**
<!-- How do you handle each of: 503 (down), 429 (rate-limited), 400 (bad
     payload), slow response (>5s), connection refused? -->

---

## 4. Degradation Policy

**Trigger threshold:**
<!-- At what memory usage level does degradation begin? How do you detect it? -->

**Shed order:**
<!-- When you must drop samples, what do you drop first and why? Which tier is
     sacrificed and in what order? -->

**Degradation mechanism:**
<!-- Do you drop samples, increase compression, apply backpressure upstream,
     or something else? What are the downstream consequences of each? -->

**Recovery:**
<!-- When memory pressure eases, how does the proxy return to normal operation?
     Is there hysteresis to prevent oscillation? -->

**What you'd do differently at 10x load:**
<!-- One concrete change to the degradation model if this handled 10x the
     current series count. -->

---

## 5. Self-Instrumentation

> Explain what each required metric means to an on-call engineer responding
> to an alert at 3am. "What question does this metric answer?"

| Metric | What it tells the on-call engineer |
|--------|-------------------------------------|
| `proxy_samples_received_total` | |
| `proxy_samples_forwarded_total` | |
| `proxy_samples_dropped_total` | |
| `proxy_buffer_bytes` | |
| `proxy_backend_requests_total` | |

**Additional metrics you expose (if any) and why:**
