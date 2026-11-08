---
title: "pagecomp: page comprehension library"
status: needs-review
last_verified: 2026-11-08
verified_against: "src/pagecomp and tests/pagecomp"
audience: contributors
---

# pagecomp

Page comprehension for AutoApply: given one reading of a web page, say what
the page is, which records it lists and where they lead, and which questions
its forms ask and how each should be treated. It is pure Python, standard
library only, and sans-IO: it never touches a browser.

```python
from pagecomp import Analyzer, observe_html

obs = observe_html(html, url=current_url, requested_url=asked_url,
                   query="backend engineer", epoch=7)
an = Analyzer(obs)
an.value("family")      # result_list / job_description / application_form / barriers / unknown
an.value("joblist")     # the job list, if the page has one, with routes per record
an.value("formread")    # one reading per question: label, type, required, FILL/TRAP/HIDDEN/...
```

Each result is `Ok`, `Abstain(reason)` or `Timeout`. A finding acted on at
a later epoch comes back as `Stale` from `Analyzer.check`.

Command line (local files only, never the network):

```
python -m pagecomp analyze page.html --url https://... --query "backend engineer"
python -m pagecomp analyze dom.json --cdp --url https://...      # a pierced DOM.getDocument
python -m pagecomp review page.html --url https://... --out review.html
python -m pagecomp bench --out pagecomp_bench.json                # S0 on this machine
```

* Design, evidence and the review protocol: `docs/BLUEPRINT.md`
* Tests: `python -m pytest -q`. Corpus tests need `PAGECOMP_CAPTURES`
  pointing at the owner captures; without it they are skipped.
