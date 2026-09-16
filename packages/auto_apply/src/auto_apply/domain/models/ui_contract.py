"""Typed vocabulary for the UI-to-backend session contract.

Why this module exists
----------------------
The entire UI-to-backend interface was one untyped dict, and the two
surfaces (CLI wizard, GUI wizard) drifted off it in opposite directions:

* The CLI wizard returns keys ``mode`` / ``keywords`` / ``location`` /
  ``max_results`` / ``strategy`` / ``links``
  (adapters/primary/cli/wizard.py:33-73). The controller reads exactly
  two: ``mode`` and ``input``
  (application/services/session_controller.py:170-171). In discovery
  mode ``input`` is absent, so ``_seed_discovery_tasks`` falls through
  to the profile's titles and locations (session_controller.py:290-302)
  and every answer the user typed is discarded. Measured by the
  maintainer on the live machine: the wizard collected exactly one
  location and the seeded queue contained two.

* The CLI wizard's paste-links mode emits ``mode="direct_links"``
  (cli/wizard.py:47), which is not in the controller's dispatch table
  (``discovery``/``direct``/``vet``/``company`` at
  session_controller.py:182-187), so the path raises ``ValueError`` at
  session_controller.py:188. The CLI's paste-your-own-links path cannot
  start at all.

* "mode" conflated two orthogonal axes. The dispatch keys select WHAT
  gets seeded (the entry axis). Where the pipeline STOPS is a separate
  concept that already exists and is honoured at every branch point
  (orchestrator._session_cap_reached, _handle_vetting,
  discovery_workflow.py:388-392, vetting_workflow.py:435-452):
  SessionExecutionMode (domain/models/session_plan.py:18). It is read
  from ``config["session"]["execution_mode"]`` (session_plan.py:171-176)
  and no ``session:`` section exists in
  resources/config/runtime_defaults.yaml (verified by reading it), so
  seven of its eight members are unreachable.

* The two URL seeders are one seeder with four literal differences
  (session_controller.py:322 vs :359): priority 1 vs 3, next_task,
  skip_vetting, source string. next_task and skip_vetting ARE the
  execution-mode axis written out longhand — one predicate answered in
  two places.

This module holds the frozen DTOs that replace the dict. Types carry
data only — never a UserProfile, never a driver, never a repository,
never an orchestrator.

Scope rule (maintainer-ruled): one source per value, chosen by natural
scope. execution_mode, entry inputs and the result cap are
session-scoped and live only in SessionRequest. Salary floor, skills,
daily limits and identity are person-scoped and live only in
UserProfile. SessionRequest deliberately shadows no profile field.

Vocabulary notes (disclosed collapses):
  * SessionReport.get_stats() emits the same counter under two names,
    ``jobs_found`` and ``jobs_discovered`` (session_report.py:340,352).
    The DTOs keep one: jobs_discovered. Legacy consumers map at the
    adapter boundary in Turn 2.
  * The CLI wizard's ``strategy`` field (adaptive/stream/collect_first,
    cli/wizard.py:51) is deliberately NOT carried: nothing reads it
    (session_controller.py reads only "mode" and "input"), and a field
    with no consumer is not typed. Removing the prompt is Turn 2's
    scope.
  * ``max_results`` is the per-search result cap for THIS session;
    None means "not declared — use the resolved SessionPlan value".
  * ``providers`` names the discovery engines for THIS session; an
    empty tuple means "not declared — use the SessionPlan's
    active_providers default". Session-scoped by nature: which engines
    this run uses is not a property of the person.

Shared menu vocabulary (stage U3, turn 3)
-----------------------------------------
Both adapters (CLI and GUI) describe the same choices to the user. The
strings and option sets below are the ONE source both surfaces read; a
label that exists only inside an adapter is a label that will drift
from the other surface. Tests assert object identity (same tuple/dict
imported by both adapters), never literal string equality.

Activity projection (stage D1)
------------------------------
The live-activity stream (``recent_events``) projects the internal
:class:`Event` vocabulary — 47 members, defined in
``domain/events.py`` — onto a small, UI-sized :class:`ActivityKind`
vocabulary defined here. ``SessionEventRecord.kind`` is an
``ActivityKind``, never the raw internal ``Event``. The mapping from
``Event`` to ``ActivityKind`` and the wording of every record's
``text`` are owned by the application layer (session_controller), so
adding, renaming, or restructuring internal bus events cannot silently
change the port's surface — and a UI adapter switching on ``kind``
switches on a vocabulary that exists for it.

Activity display vocabulary (stage D2)
--------------------------------------
Both dashboards print the stream. The sentence each record carries
(``SessionEventRecord.text``) is rendered once, in the application
layer; what the two surfaces share here is only the PRESENTATION of
that sentence: one mark per kind (``ACTIVITY_MARKS``) and one line
format (``format_activity_line``). A mark or line format defined
inside an adapter is a second way of saying the same thing — the drift
this arc exists to remove — so both adapters import these, and the
parity pin in tests/adapters/test_activity_feed.py asserts both call
``format_activity_line`` rather than composing their own line.

Autonomy vocabulary (stage E1)
------------------------------
``SessionSnapshot.autonomy_enabled`` and
``SessionSummary.autonomy_enabled`` label whether THIS session submits
without per-submission review. The value is computed by the controller
at its construction from the checkpoints the interrupt policy was built
from — it is a frozen statement about the session, so a run with
autonomy on is labelled data, not spoiled data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan


# ─────────────────────────────────────────────────────────────────────────────
# EntryPoint — how a session's initial work enters the queue
# ─────────────────────────────────────────────────────────────────────────────

class EntryPoint(Enum):
    """How a session's initial work enters the queue.

    One member per existing seeder in session_controller.py:
        SEARCH         → _seed_discovery_tasks (session_controller.py:275)
        DIRECT_URLS    → _seed_direct_apply_tasks (session_controller.py:322)
        VET_URLS       → _seed_vet_tasks (session_controller.py:359)
        COMPANY_PAGES  → _seed_company_tasks (session_controller.py:395)
    """

    SEARCH = auto()
    DIRECT_URLS = auto()
    VET_URLS = auto()
    COMPANY_PAGES = auto()


_ENTRY_LABEL_ALIASES: dict[str, EntryPoint] = {
    # The controller's dispatch keys (session_controller.py:182-187):
    "discovery": EntryPoint.SEARCH,
    "direct": EntryPoint.DIRECT_URLS,        # GUI wizard (gui/wizard.py:74)
    "vet": EntryPoint.VET_URLS,
    "company": EntryPoint.COMPANY_PAGES,
    # The CLI wizard's vocabulary (cli/wizard.py:47) — today "direct_links"
    # is not in the dispatch table and raises ValueError at
    # session_controller.py:188. The CLI paste-links path cannot start at all.
    "direct_links": EntryPoint.DIRECT_URLS,
    # Canonical names, accepted for completeness:
    "search": EntryPoint.SEARCH,
    "direct_urls": EntryPoint.DIRECT_URLS,
    "vet_urls": EntryPoint.VET_URLS,
    "company_pages": EntryPoint.COMPANY_PAGES,
}


def entry_point_from_label(label: str) -> EntryPoint:
    """Resolve a UI-provided mode label to an EntryPoint.

    This is the single place that answers "what does this label mean" —
    the CLI wizard, the GUI wizard, and the controller's dispatch table
    were three answering sites, and two of them disagreed with the third.

    Args:
        label: The raw mode string from a wizard or a legacy dict.

    Returns:
        The EntryPoint for the label.

    Raises:
        ValueError: For an unknown label. The boundary moves earlier than
            today's failure at session_controller.py:188, which only fires
            after initialize_session has been entered.
    """
    try:
        return _ENTRY_LABEL_ALIASES[label.strip().lower()]
    except KeyError:
        raise ValueError(
            f"unknown entry label {label!r}. Valid labels: "
            f"{sorted(_ENTRY_LABEL_ALIASES)}"
        ) from None


# ─────────────────────────────────────────────────────────────────────────────
# SessionViewState — UI-facing session state
# ─────────────────────────────────────────────────────────────────────────────

class SessionViewState(Enum):
    """UI-facing session state — deliberately NOT AgentState.

    AgentState (application/agent/state_machine.py) has no member for
    "no session has been started" or "the session ended, choose again";
    IDLE means "orchestrator alive, queue drained". Those two situations
    exist only in the UI's vocabulary, so the port keeps its own small
    enum and the controller maps between them via
    view_state_from_agent_state.
    """

    NO_SESSION = auto()     # no session has been started
    READY = auto()          # seeded and configured, waiting for start()
    RUNNING = auto()        # orchestrator alive and working (incl. AgentState.IDLE)
    PAUSED = auto()
    AWAITING_HUMAN = auto()
    STOPPING = auto()
    COMPLETE = auto()       # ended cleanly; a new session may be started
    FAILED = auto()


_AGENT_STATE_TO_VIEW_STATE: dict[str, SessionViewState] = {
    "IDLE": SessionViewState.RUNNING,
    "INITIALIZING": SessionViewState.RUNNING,
    "RUNNING": SessionViewState.RUNNING,
    "DISCOVERING": SessionViewState.RUNNING,
    "VETTING": SessionViewState.RUNNING,
    "APPLYING": SessionViewState.RUNNING,
    "PAUSED": SessionViewState.PAUSED,
    "RESOLVING_CAPTCHA": SessionViewState.RUNNING,
    "RESOLVING_LOGIC_CONFLICT": SessionViewState.RUNNING,
    "AWAITING_HUMAN": SessionViewState.AWAITING_HUMAN,
    "ERROR_RECOVERY": SessionViewState.RUNNING,
    "STOPPING": SessionViewState.STOPPING,
    "STOPPED": SessionViewState.COMPLETE,
    "FAILED": SessionViewState.FAILED,
}


def view_state_from_agent_state(state_name: str) -> SessionViewState:
    """Map an AgentState member name to a SessionViewState.

    Takes the name as a string because this module is in the domain layer
    and AgentState lives in the application layer — domain may not import
    application (the boundary pin in tests/test_architecture.py scans
    src/). The controller (application layer) calls this.

    Args:
        state_name: An AgentState member name, e.g. "RUNNING".

    Returns:
        The SessionViewState for that name.

    Raises:
        ValueError: For a name with no mapping. When you add an AgentState
            member, add it to _AGENT_STATE_TO_VIEW_STATE above — the
            totality pin (tests/domain/test_ui_contract.py) fails until
            you do.
    """
    try:
        return _AGENT_STATE_TO_VIEW_STATE[state_name]
    except KeyError:
        raise ValueError(
            f"AgentState name {state_name!r} has no SessionViewState "
            f"mapping — add it to _AGENT_STATE_TO_VIEW_STATE in "
            f"domain/models/ui_contract.py"
        ) from None


# ─────────────────────────────────────────────────────────────────────────────
# ActivityKind — the UI-sized vocabulary of the live-activity stream
# ─────────────────────────────────────────────────────────────────────────────

class ActivityKind(Enum):
    """The vocabulary a UI adapter may switch on for the activity feed.

    Ten members, versus the 47 internal :class:`Event` members the stream
    is projected FROM. ``SessionEventRecord.kind`` carries this enum —
    never the raw internal ``Event`` — so the EventBus stays free to add,
    rename, or restructure internal events without the port's surface
    changing. The mapping from ``Event`` to ``ActivityKind`` and every
    record's ``text`` are owned by the application layer
    (session_controller); a pin
    (tests/application/test_ui_port_conformance.py) asserts every
    subscribed event maps to exactly one kind and every kind is
    reachable, so adding a subscription without deciding its kind fails
    loudly.
    """

    FOUND = auto()      # jobs were discovered
    VETTED = auto()     # a job passed vetting
    REJECTED = auto()   # a job was rejected by vetting
    APPLIED = auto()    # an application was submitted
    SKIPPED = auto()    # duplicate or user-declined work
    BLOCKED = auto()    # an access barrier stopped the work
    REFUSED = auto()    # the submission gate or a policy said no
    FAILED = auto()     # the work failed for another reason
    INFO = auto()       # neutral operational note
    WAITING = auto()    # the agent is waiting for the human


# ─────────────────────────────────────────────────────────────────────────────
# DTOs — frozen, validated on construction
# ─────────────────────────────────────────────────────────────────────────────

class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class SessionRequest(_FrozenModel):
    """What the user asked this session to do. Session-scoped only.

    The two axes are separate fields: ``entry`` says what gets seeded
    (replacing the dispatch keys), ``execution_mode`` says how far the
    pipeline goes (replacing next_task/skip_vetting longhand). With both
    typed, "direct_links" is unspellable rather than merely unspelled.

    Deliberately omitted (see module docstring): the wizard's ``strategy``
    field (no reader today), and every person-scoped profile field.

    ``providers`` names the discovery engines for THIS session; an empty
    tuple means "not declared — use the SessionPlan's active_providers
    default". Session-scoped by nature: which engines this run uses is
    not a property of the person. The controller threads a non-empty
    tuple into the rebuilt plan's ``active_providers``, and
    DiscoveryWorkflow's fan-out filters by that field — so a request
    naming one engine runs one engine.
    """

    entry: EntryPoint
    execution_mode: SessionExecutionMode = SessionExecutionMode.FULL_PIPELINE
    keywords: tuple[str, ...] = ()
    location: str = ""
    max_results: int | None = None
    urls: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()

    @property
    def seed_priority(self) -> int:
        """Queue priority for the link-seeding path (RESOLVE_JOB_URL).

        Preserves the literal 1-vs-3 split between the two URL seeders
        (session_controller.py:322 vs :359): pasted apply-URLs jump ahead
        of vet-URLs. The split is derived from execution_mode, not from
        the entry point: APPLY_ONLY skips vetting, so its URLs go first.

        These literals deliberately sit above the discovery-pipeline bands
        (TaskPriority.DISCOVER is 100) because user-initiated work outranks
        pipeline work (domain/models/task_priority.py docstring).
        """
        return 1 if not self.execution_mode.includes_vetting else 3

    def is_actionable(self) -> bool:
        """Whether this request can seed any task at all.

        SEARCH is always actionable: an empty keyword list falls back to
        the profile's desired_job_titles (session_controller.py:290-302).
        The link entry points need at least one URL.
        """
        if self.entry is EntryPoint.SEARCH:
            return True
        return bool(self.urls)


class SessionSnapshot(_FrozenModel):
    """The every-500-ms poll view.

    Always constructible, including with no session at all:
    ``SessionSnapshot()`` IS the null object for the no-session case
    (see ui_port.py for the ruling). All counters zero, state NO_SESSION.
    Mirrors the fields the dashboards poll (cli/dashboard.py:245-260,
    gui/app.py:494-499) plus ``current_task`` — the CLI dashboard's own
    P2-cleanup item (cli/dashboard.py:170 reads
    orchestrator.context.current_work_unit directly today).
    """

    state: SessionViewState = SessionViewState.NO_SESSION
    jobs_discovered: int = 0
    jobs_vetted: int = 0
    applications_submitted: int = 0
    applications_failed: int = 0
    queue_pending: int = 0
    pending_approvals: int = 0
    duration_seconds: float = 0.0
    current_task: str = ""
    autonomy_enabled: bool = False


class SubmittedApplication(_FrozenModel):
    """One submitted application, for the results view."""

    url: str
    company: str
    outcome: str


class DiscoveredJob(_FrozenModel):
    """One job found by discovery, for the results view.

    This is the payoff of a collect-links run: title, company, and the
    URL a person can open by hand. Read from job_history (which C1
    persists at discovery with session_id), never from the live
    pipeline — the list must survive even a hard kill.
    """

    title: str
    company: str
    url: str
    source: str = ""


class SessionSummary(_FrozenModel):
    """The end-of-session / results view.

    Mirrors SessionReport.get_stats() (session_report.py:338) as typed
    data. Constructible with no session at all (the null object ruling):
    ``SessionSummary()`` is the no-session summary, zeroed.
    """

    state: SessionViewState = SessionViewState.NO_SESSION
    jobs_discovered: int = 0
    jobs_vetted: int = 0
    jobs_passed_vetting: int = 0
    applications_attempted: int = 0
    applications_submitted: int = 0
    applications_failed: int = 0
    submissions_blocked_by_gate: int = 0
    gate_block_remedy: str = ""
    success_rate: float = 0.0
    duration_seconds: float = 0.0
    total_task_duration_seconds: float = 0.0
    average_application_seconds: float | None = None
    submitted: tuple[SubmittedApplication, ...] = ()
    discovered: tuple[DiscoveredJob, ...] = ()
    report_path: Path | None = None
    autonomy_enabled: bool = False

    @property
    def duration_str(self) -> str:
        """HH:MM:SS, the shape both dashboards print today."""
        total = int(self.duration_seconds)
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"

    @property
    def submitted_urls(self) -> tuple[str, ...]:
        """Convenience projection for the legacy results view (cli/startup.py:467)."""
        return tuple(a.url for a in self.submitted)

    @property
    def submitted_companies(self) -> dict[str, str]:
        """URL → company projection for the legacy results view (cli/startup.py:474)."""
        return {a.url: a.company for a in self.submitted}


class QueueSnapshot(_FrozenModel):
    """The work-queue view, mirroring get_queue_stats (session_controller.py:543)."""

    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    permanently_failed: int = 0


class ApprovalRequest(_FrozenModel):
    """One open HITL gate, mirroring the payload of get_pending_approvals
    (session_controller.py:522-532). Empty tuple means no gate is open."""

    context_id: str
    checkpoint: str
    question: str
    options: tuple[str, ...] = ()


class SessionEventRecord(_FrozenModel):
    """One recent event for the live-activity stream.

    Display-shaped only: the structured payload stays on the EventBus;
    the port's stream carries a projected :class:`ActivityKind` and the
    rendered sentence a log viewer prints. ``kind`` is deliberately NOT
    the raw internal ``Event`` — see :class:`ActivityKind` for why.
    ``text`` names the job title and company where applicable and never
    the applicant's name, email, phone, or address.
    """

    kind: ActivityKind
    text: str
    level: str = "INFO"
    at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class SessionHistoryEntry(_FrozenModel):
    """One past session, read from its saved report file.

    Built by the controller from SessionReport.list_reports() output.
    ``completion_state`` comes from C1's report field — reports written
    before that field existed read as "unknown" rather than guessing.
    """

    session_id: str = ""
    profile_name: str = ""
    mode: str = "discovery"
    completion_state: str = "unknown"
    started_at: str = ""
    finished_at: str | None = None
    duration_seconds: float = 0.0
    jobs_found: int = 0
    jobs_vetted: int = 0
    applications_submitted: int = 0
    applications_failed: int = 0
    report_path: Path | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Shared menu vocabulary (stage U3, turn 3)
# ─────────────────────────────────────────────────────────────────────────────
#
# Both adapters (CLI and GUI) describe the same choices to the user. The
# strings and option sets below are the ONE source both surfaces read; a
# label that exists only inside an adapter is a label that will drift from
# the other surface. The parity pin asserts object identity (both adapters
# import the same tuple/dict), never literal string equality.

#: User-facing labels for the four entry points, in menu order. The GUI
#: renders these as its entry radio group; the CLI's mode prompt is numeric
#: and predates this vocabulary, so it does not render them (yet).
ENTRY_POINT_LABELS: dict[EntryPoint, str] = {
    EntryPoint.SEARCH: "Find jobs for me",
    EntryPoint.DIRECT_URLS: "Apply to links I paste",
    EntryPoint.VET_URLS: "Check links I paste, then apply",
    EntryPoint.COMPANY_PAGES: "Scan a company's careers page",
}

#: Exit-axis options for a discovery run (SEARCH and COMPANY_PAGES), in menu
#: order; the first entry is the menu default. "Collect" options exist only
#: where the pipeline discovers the jobs itself.
SEARCH_OUTCOME_OPTIONS: tuple[tuple[str, SessionExecutionMode], ...] = (
    ("Collect, check, and apply (default)", SessionExecutionMode.FULL_PIPELINE),
    ("Collect and check only — nothing is submitted", SessionExecutionMode.DISCOVER_AND_VET),
    ("Collect links only — nothing is submitted", SessionExecutionMode.DISCOVER_ONLY),
)

#: Exit-axis options for pasted apply-links (DIRECT_URLS), in menu order;
#: the first entry is the menu default. "Collect" options are impossible
#: when the user supplied the links, so they do not appear.
URL_OUTCOME_OPTIONS: tuple[tuple[str, SessionExecutionMode], ...] = (
    ("Apply to them now (default)", SessionExecutionMode.APPLY_ONLY),
    ("Check them first, then apply to the ones that pass", SessionExecutionMode.VET_AND_APPLY),
)

#: Exit-axis options for pasted vet-links (VET_URLS), in menu order; the
#: first entry is the menu default. VET_ONLY appears here — and only here —
#: as the no-submit outcome for pasted links (decided at stage U3 turn 3:
#: B2 kept it off-menu only because the CLI wizard offers no VET_URLS entry;
#: the GUI offers the entry, so the matching no-submit outcome is offered).
VET_OUTCOME_OPTIONS: tuple[tuple[str, SessionExecutionMode], ...] = (
    ("Check them first, then apply to the ones that pass (default)", SessionExecutionMode.VET_AND_APPLY),
    ("Check them only — nothing is submitted", SessionExecutionMode.VET_ONLY),
)


def outcome_options_for_entry(
    entry: EntryPoint,
) -> tuple[tuple[str, SessionExecutionMode], ...]:
    """The exit-axis options for an entry point, in menu order.

    The first entry is the menu default and MUST equal
    ``_LEGACY_ENTRY_TO_EXECUTION_MODE[entry]`` (locked by a guard pin in
    tests/adapters/test_gui_wizard.py) — the menu default and the legacy
    meaning of the entry label are the same fact, so they are pinned to
    stay equal rather than trusted to stay equal.

    "Collect" options exist only where the pipeline discovers jobs itself
    (SEARCH, COMPANY_PAGES); pasted links cannot be "collected".
    """
    if entry is EntryPoint.DIRECT_URLS:
        return URL_OUTCOME_OPTIONS
    if entry is EntryPoint.VET_URLS:
        return VET_OUTCOME_OPTIONS
    return SEARCH_OUTCOME_OPTIONS


def provider_vocabulary() -> tuple[str, ...]:
    """The engine names a user may select for discovery.

    Read from SessionPlan.active_providers' field default — one source — so
    an engine added to the plan vocabulary appears in both wizards
    automatically. Never hardcode this list in an adapter.
    """
    return tuple(SessionPlan.model_fields["active_providers"].default)


# ─────────────────────────────────────────────────────────────────────────────
# Shared display vocabulary for the activity stream (stage D2)
# ─────────────────────────────────────────────────────────────────────────────
#
# The sentence a record carries (SessionEventRecord.text) is rendered once
# in the application layer. What the two dashboards share here is ONLY the
# presentation of that sentence: one mark per kind and one line format. A
# mark map or a line format defined inside an adapter is a second way of
# saying the same thing — the drift this arc exists to remove — so both
# adapters import these, and the parity pin
# (tests/adapters/test_activity_feed.py) asserts both call
# format_activity_line rather than composing their own line.

#: One display mark per ActivityKind, in the shape the GUI mockup already
#: describes ("a timestamp, a mark, and one line"). Chosen to be
#: distinguishable at a glance on a small screen; logging_setup's
#: backslashreplace protection keeps them safe on cp1252 consoles.
ACTIVITY_MARKS: dict[ActivityKind, str] = {
    ActivityKind.FOUND: "\U0001F50D",      # 🔍 magnifier
    ActivityKind.VETTED: "\u2713",          # ✓ check
    ActivityKind.REJECTED: "\u2717",        # ✗ cross
    ActivityKind.APPLIED: "\U0001F4E4",     # 📤 outbox
    ActivityKind.SKIPPED: "\u23ED",         # ⏭ next
    ActivityKind.BLOCKED: "\u26D4",         # ⛔ no entry
    ActivityKind.REFUSED: "\u2298",         # ⊘ slashed circle
    ActivityKind.FAILED: "\u2716",          # ✖ heavy cross
    ActivityKind.INFO: "\u00B7",            # · middle dot
    ActivityKind.WAITING: "\u23F3",         # ⏳ hourglass
}


def format_activity_line(record: SessionEventRecord) -> str:
    """The one line both dashboards print for one activity record.

    Returns ``HH:MM:SS <mark> <text>`` — the timestamp from the record,
    the mark from ACTIVITY_MARKS, and the record's ``text`` VERBATIM from
    the application layer. Neither adapter composes its own sentence; if
    you are about to edit this to decorate the text, the edit belongs in
    session_controller's renderers, not here.
    """
    return f"{record.at:%H:%M:%S} {ACTIVITY_MARKS[record.kind]} {record.text}"


def activity_new(
    records: tuple[SessionEventRecord, ...],
    last_displayed: SessionEventRecord | None,
) -> tuple[SessionEventRecord, ...]:
    """The records after ``last_displayed`` in the current window.

    Index-based diffing starves permanently once the bounded deque wraps
    (the window's contents shift but a saved index does not move), so this
    diffs by record identity instead. When ``last_displayed`` has fallen
    out of the window (deque wrapped, or a new session started), the whole
    current window is returned — a bounded replay, never silence.

    Records with identical kind/text/level in the same second compare
    equal, and that is correct: for display they are the same record.
    """
    if last_displayed is None:
        return tuple(records)
    try:
        index = records.index(last_displayed)
    except ValueError:
        return tuple(records)
    return tuple(records[index + 1:])
