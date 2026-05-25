---
name: fix-parser
description: >-
  Fixes PVS-Studio JSON parser breakage when report format changes between
  versions. Use when parser.py fails, unknown JSON keys appear, upload crashes
  on new PVS reports, or tests/test_parser.py needs updates.
---

# Fix PVS-Studio JSON Parser

Parent skill: [pvs-tracker-dev](../pvs-tracker-dev/SKILL.md). Constraints: [.cursor/rules.md](../../rules.md) §6, [.cursor/spec.md](../../spec.md).

## Symptom

Parser fails on PVS-Studio report vX.Y.Z — field names or structure differ from what `parser.py` expects.

## Rules (non-negotiable)

- Use `.get()` with sensible defaults on every JSON field.
- Log **warnings** for unknown keys (`logger.warning`), never `print()`.
- Do **not** fail the whole upload — skip bad warnings or mark them skipped.
- Preserve fingerprint: `file:line:code:message` via `compute_fingerprint()`.
- Normalize paths: `file.replace("\\", "/").strip()`.
- Empty file → synthetic path `__analysis__/{code}` (do not skip; see `parser.py`).

## Workflow

```
Task Progress:
- [ ] Reproduce: capture failing JSON snippet or test fixture
- [ ] Read parser.py + tests/test_parser.py
- [ ] Patch extraction helpers (_extract_*, safe_to_int)
- [ ] Add/adjust unit test for new format variant
- [ ] Run pytest tests/test_parser.py
- [ ] Smoke: POST /api/v1/upload still returns 200
```

## Files to touch

| File | Change |
|------|--------|
| `pvs_tracker/parser.py` | Resilient field extraction |
| `tests/test_parser.py` | Modern + legacy format cases |
| `tests/conftest.py` | Only if new fixtures needed |

Do **not** change `incremental.py` unless fingerprint inputs change.

## Patterns

```python
value = warning.get("fieldName", default)
if "unknownKey" in warning:
    logger.warning("Unknown PVS key: %s", "unknownKey")
```

```python
line = safe_to_int(pos.get("line")) or 0
```

Handle both formats already in codebase:
- **Modern:** numeric `level`, `positions[]`, nested structure
- **Legacy:** string `severity`, flat fields

## Verification

```bash
pytest tests/test_parser.py -v
pytest tests/test_smoke.py -k upload -v
```

End with:

```text
✅ Файл готов. Запусти: pytest tests/test_parser.py -v
Ожидаемый результат: все тесты парсера зелёные; upload не падает на новом отчёте.
```

## MCP

Use **sqlite** only if upload succeeds but issues look wrong (data issue, not parse crash). Use **filesystem** to read sample reports under `reports/`.
