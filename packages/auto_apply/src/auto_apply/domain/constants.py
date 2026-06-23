"""
AA Domain Constants
===================
Single source of truth for all fixed, non-configurable identifiers.
"""
from __future__ import annotations

BROWSER_CLOSED_ERRORS: frozenset[str] = frozenset({
    "target window already closed",
    "invalid session id",
    "no such window",
    "no such session",
    "disconnected: not connected to devtools",
    "connection refused",
    "session deleted",
    "chrome not reachable",
    "failed to decode response from marionette",
    "execution context was destroyed",
    "target closed",
})

ABOUT_BLANK: str = "about:blank"
ABOUT_NEWTAB: str = "about:newtab"
INTERNAL_PAGE_PREFIXES: tuple[str, ...] = ("about:","chrome://","chrome-extension://","moz-extension://","edge://","data:")
DOCUMENT_READY: str = "complete"
DOCUMENT_INTERACTIVE: str = "interactive"

ATS_GREENHOUSE: str = "greenhouse"
ATS_LEVER: str = "lever"
ATS_WORKDAY: str = "workday"
ATS_ICIMS: str = "icims"
ATS_TALEO: str = "taleo"
ATS_ASHBY: str = "ashby"
ATS_BAMBOOHR: str = "bamboohr"
ATS_RIPPLING: str = "rippling"
ATS_WORKABLE: str = "workable"
ATS_SMARTRECRUITERS: str = "smartrecruiters"
ATS_JOBVITE: str = "jobvite"
ATS_RECRUITEE: str = "recruitee"
ATS_GUSTO: str = "gusto"
ATS_PINPOINTHQ: str = "pinpointhq"
ATS_UNKNOWN: str = "unknown"

ENGINE_GOOGLE: str = "google"
ENGINE_BING: str = "bing"
ENGINE_DUCKDUCKGO: str = "duckduckgo"
ENGINE_INDEED: str = "indeed"
ENGINE_LINKEDIN: str = "linkedin"

LINEAR_MODE_PLATFORMS: frozenset[str] = frozenset({ENGINE_LINKEDIN, ENGINE_INDEED})

TASK_DISCOVER: str = "DISCOVER"
TASK_DISCOVER_COMPANY: str = "DISCOVER_COMPANY"
TASK_VET: str = "VET"
TASK_APPLY: str = "APPLY"
TASK_HANDLE_CAPTCHA: str = "HANDLE_CAPTCHA"

SIG_GJ_01: str = "GJ-01"
SIG_GJ_02: str = "GJ-02"
SIG_GJ_03: str = "GJ-03"
SIG_GJ_04: str = "GJ-04"
SIG_GJ_05: str = "GJ-05"
SIG_DISC_01: str = "DISC-01"
SIG_DISC_02: str = "DISC-02"
SIG_DISC_03: str = "DISC-03"
SIG_DISC_04: str = "DISC-04"
SIG_DISC_05: str = "DISC-05"
SIG_DISC_06: str = "DISC-06"
SIG_QS_01: str = "QS-01"
SIG_QS_02: str = "QS-02"
SIG_QS_03: str = "QS-03"
SIG_QS_04: str = "QS-04"
SIG_QS_05: str = "QS-05"
SIG_ST_01: str = "ST-01"
SIG_ST_02: str = "ST-02"
SIG_ST_03: str = "ST-03"
SIG_ST_04: str = "ST-04"
SIG_DP_01: str = "DP-01"
SIG_DP_02: str = "DP-02"
SIG_DP_03: str = "DP-03"
SIG_DP_04: str = "DP-04"
SIG_DP_05: str = "DP-05"
SIG_RC_01: str = "RC-01"
SIG_RC_02: str = "RC-02"
SIG_RC_03: str = "RC-03"

# AI Hiring System Bias signals
SIG_AH_01: str = "AH-01"  # ATS knockout question pattern analysis
SIG_AH_02: str = "AH-02"  # Readability/complexity asymmetry

# Labor Market Macro-Signals (corpus-level, computed by macro_analysis.py)
SIG_LM_01: str = "LM-01"  # Sector opening-to-application ratio
SIG_LM_02: str = "LM-02"  # Application black hole mapping
SIG_LM_03: str = "LM-03"  # Geographic pay compression by demographics

SEVERITY_FLAG: str = "flag"
SEVERITY_CONCERN: str = "concern"
SEVERITY_VIOLATION: str = "violation"

RESEARCH_SCHEMA_VERSION: int = 2
RESEARCH_SALT_ENV_VAR: str = "AA_RESEARCH_SALT"

# ── EventBus Event Names (Research Module) ───────────────────────────────────
# Published by application workflows when research-relevant data becomes
# available. ResearchSignalAggregator subscribes to all of these.
# Handlers MUST follow the queue-plus-daemon-thread pattern (no I/O on the
# publishing thread) — see ResearchSignalAggregator.submit_context().

EVENT_JOB_POSTING_OBSERVED: str = "JOB_POSTING_OBSERVED"
EVENT_FORM_OBSERVED: str = "FORM_OBSERVED"
EVENT_APPLICATION_OUTCOME_OBSERVED: str = "APPLICATION_OUTCOME_OBSERVED"
EVENT_SALARY_OBSERVED: str = "SALARY_OBSERVED"

# Fired by signal detectors after run_all_detectors() — informational,
# primarily for GUI dashboards / live research feed display.
EVENT_RESEARCH_SIGNAL_DETECTED: str = "RESEARCH_SIGNAL_DETECTED"

# ── Research Consent ───────────────────────────────────────────────────────────
# Current consent dialog version. Increment whenever the data collection
# practices documented in docs/ETHICS.md change. Stored with every signal.
CURRENT_CONSENT_VERSION: str = "2.1"
