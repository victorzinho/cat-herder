## Context

Imports **fail silently** when _meteo_ times out in **`fetch()`**, see [the runbook](https://example.com/runbook) and ~~the old notes~~.
Ask @Ana 🔥 before 2026-11-04, now BLOCKED: https://example.atlassian.net/browse/SAT-9

- Retry
- Alert
  3. Slack
  4. Mail

- [x] Reproduce
- [ ] Fix
  - [ ] Test

```python
client.get(url,
           timeout=30)
```

> Provider says:
>
> it's on our side

> Retries are capped at 3.

---

| Provider | Timeout |
| --- | --- |
| meteo \| backup | 30 s |

**Logs**

See trace.log

Left

Right
