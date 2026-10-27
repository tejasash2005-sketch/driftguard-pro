## DriftGuard: simulated-regression - **FAIL**

Run `b22721c0b212` | 8 cases | pass rate 62.5% (weighted 63.0%) | 3 failed, 0 errors, 0 inconclusive

| Case | Status | Reasons |
|---|---|---|
| `refund_policy` | FAIL | latency increased 117.1% (limit 50.0%) |
| `summary` | FAIL | non_empty: output is empty; text similarity 0.000 is below the minimum 0.750 |
| `classification` | FAIL | json_keys: missing keys: category; text similarity 0.530 is below the minimum 0.750; JSON structure changed: removed category |

| Metric | n | Mean diff | CI | p | Significant |
|---|---|---|---|---|---|
| similarity | 8 | 0.8563 | [0.6364, 1] | n/a | not tested |
| latency_ms | 8 | 107.3 | [-17.23, 343.5] | 0.5938 | no |
| total_tokens | 8 | 1.074 | [0.1111, 1.857] | 0.09375 | no |
| cost_usd | 8 | 2.148e-06 | [2.222e-07, 3.714e-06] | 0.09375 | no |

