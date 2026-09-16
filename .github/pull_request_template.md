## What and why

Task: <C-S0 / N-S2 ...> · Key result or checklist item: <CP2-KR2 / D1 ...>

<one paragraph: what this changes and why now>

## How to test

```
python -m pytest test/ -q
```

<UI: steps and a screenshot>

## Evidence

<test output · FakeLLM call counts · eval numbers before/after · screenshot>

## Checklist

- [ ] Tests added or updated (failing-first for bug fixes)
- [ ] No real or redacted tender or bid data, no secrets
- [ ] Migration reversible (if any)
- [ ] Prompt version bumped and eval attached (if a prompt changed)
- [ ] API contract snapshot updated and PR labelled `contract` (if the API changed)
- [ ] No document text in logs
