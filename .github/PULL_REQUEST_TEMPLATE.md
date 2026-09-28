## What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The problem, not the solution. If it fixes an issue: Fixes #123 -->

## How it was verified

<!-- Required. "I ran it" is a verification; "it should work" is not.
     Paste the relevant gate output or describe the live run. -->

```
```

## Checklist

- [ ] All four gates pass locally:
      `pytest tests -q -p no:cacheprovider -rs` ·
      `ruff check src --select F821` ·
      `mypy src/auto_apply` ·
      `mypy --explicit-package-bases tests`
- [ ] Documentation updated **in this PR** if behaviour changed
- [ ] `CHANGELOG.md` updated under **Unreleased**
- [ ] An ADR is included, or none is needed (see CONTRIBUTING §5)
- [ ] Nothing was deleted — obsolete files went through `retire.py`
- [ ] No personal data in the diff, the tests, or the fixtures

## Pins added or changed

<!-- For each new test, state its label and whether it was shown to FAIL
     before the fix. A pin that passed the moment you wrote it has no teeth. -->

| Test | Label (teeth / differential / coverage / characterisation / guard) | Shown failing first? |
| --- | --- | --- |
|  |  |  |

**Predicted suite count after this change:** <!-- e.g. 1384 → 1391 passed -->

## Risk

<!-- What could this break that the gates would not catch?
     Which tier does it trade against (see GOVERNANCE.md)? -->

## Screenshots

<!-- UI changes only. REDACT: AA screenshots routinely contain real names,
     addresses and employment history. -->
