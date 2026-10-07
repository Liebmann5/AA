"""The uninstall engine: plan, execute, verify.

Order of operations (execute): validate -> stop this process's research
observer -> stop every other registered AA process and any browser AA
launched -> research-data step (hold / keep / export / delete /
keep-in-place) -> guarded deletion of everything AA created -> detached
finisher for the runtime AA cannot delete itself -> verify and report.

Two inviolable rules, structurally enforced rather than documented:

  * every delete passes through guarded_remove (scoping.require_deletable
    re-resolves and re-judges each path immediately before it is removed);
  * research records are never destroyed by default — they are kept (in
    place, moved, or exported to a confirmed location) unless the user
    explicitly chooses deletion, and a research retention hold makes
    destruction a refusal no flag can override (45 CFR 46.115(b): the
    protocol's retention period outlives the tool).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

import psutil

from auto_apply.application.services.footprint_ledger import FootprintLedger
from auto_apply.application.services.install.manifest import (
    MANAGED_RECEIPT_ENTRIES,
    RECEIPT_NAME,
    load_manifest,
)
from auto_apply.application.services.instance_registry import InstanceRegistry
from auto_apply.application.services.uninstall.finisher import launch_detached
from auto_apply.application.services.uninstall.guarded_delete import guarded_remove
from auto_apply.application.services.uninstall.model import (
    GROUP_AA,
    GROUP_INSTALL,
    GROUP_PREEXISTING,
    GROUP_RESEARCH,
    Leftover,
    PlanItem,
    RetentionHold,
    UninstallDecision,
    UninstallPlan,
    UninstallReport,
)
from auto_apply.application.services.uninstall.scoping import (
    OutOfScopeError,
    is_within,
)
from auto_apply.domain.config import CREATION_MARKER_NAME
from auto_apply.domain.constants import WITHDRAWAL_NOTICE_FILENAME


class UninstallRefused(RuntimeError):
    """The uninstall cannot proceed as asked — said before anything happens."""


#: Top-level entries AA is known to create inside the data home, beyond the
#: names the environment already carries. Deletion is by PROOF, not by
#: folder (D2): anything not in this set or the env-derived names is
#: reported "not AA's — left in place" and never removed. Add new data-home
#: residents here when they are introduced; an unlisted AA file is left, not
#: deleted — the safe direction.
DATA_ROOT_KNOWN_ENTRIES: frozenset[str] = frozenset(
    {
        "profiles",
        "logs",
        "aa_data.db",
        "checkpoints",
        "screenshots",
        "reports",
        "tmp",
        "annotations",
        "detector_samples",
        "page_feedback.db",
        "harvest_baselines.db",
        "selector_confidence.json",
        "cache",
        CREATION_MARKER_NAME,
    }
)

#: The frozen build's own runtime entries (the data home is governed by the
#: data-root rules, not this set). The folder or drive the exe sits in is
#: NEVER AA-created and never a deletion target (D1).
FROZEN_KNOWN_ENTRIES: frozenset[str] = frozenset({"AutoApply.exe", "_internal"})


@dataclass
class UninstallEnvironment:
    """Everything the engine needs, injectable so tests stay hermetic.

    consent_factory is called ONLY when the consent database already exists
    (its constructor creates the schema — the uninstall path must create
    nothing). home is injectable so tests never scan the real home directory.
    """

    run_mode: str
    data_root: Path
    install_root: Path | None
    ledger_path: Path
    instances_dir: Path
    research_dir: Path
    research_db: Path
    consent_db: Path
    provenance_key: Path
    research_salt: Path
    page_copies_dir: Path
    hold_path: Path
    browser_profile_dir: Path
    consent_factory: Callable[[], Any] | None = None
    export_bundle: Callable[[Path, str], Any] | None = None
    verify_bundle: Callable[[Path], Any] | None = None
    realpath: Callable[[str], str] = os.path.realpath
    today: str = ""
    home: Path = field(default_factory=Path.home)
    progress: Callable[[str], None] | None = None
    processes: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        if not self.today:
            self.today = date.today().isoformat()

    @classmethod
    def from_config(
        cls,
        *,
        consent_factory: Callable[[], Any] | None = None,
        export_bundle: Callable[[Path, str], Any] | None = None,
        verify_bundle: Callable[[Path], Any] | None = None,
    ) -> "UninstallEnvironment":
        """The real environment, resolved through the one paths authority."""
        from auto_apply.domain import config as cfg  # noqa: PLC0415

        return cls(
            run_mode=cfg.get_run_mode(),
            data_root=cfg.USER_DATA_DIR,
            install_root=cfg.get_install_root(),
            ledger_path=cfg.FOOTPRINT_LEDGER_PATH,
            instances_dir=cfg.INSTANCES_DIR,
            research_dir=cfg.RESEARCH_DIR,
            research_db=cfg.RESEARCH_DB_PATH,
            consent_db=cfg.USER_DATA_DIR / "research_consent.db",
            provenance_key=cfg.PROVENANCE_KEY_PATH,
            research_salt=cfg.RESEARCH_SALT_PATH,
            page_copies_dir=cfg.PAGE_COPIES_DIR,
            hold_path=cfg.RESEARCH_HOLD_PATH,
            browser_profile_dir=cfg.BROWSER_PROFILE_DIR,
            consent_factory=consent_factory,
            export_bundle=export_bundle,
            verify_bundle=verify_bundle,
        )


class UninstallEngine:
    """Plan, execute, verify. See the module docstring for the order."""

    def __init__(self, env: UninstallEnvironment) -> None:
        self.env = env
        self._manager: Any = None

    # ── retention hold ───────────────────────────────────────────────────

    def read_hold(self) -> RetentionHold | None:
        """The hold on this device, or None. Unparseable file = no hold; an
        unparseable hold_until inside a valid file reads as ACTIVE (the
        RetentionHold.active rule: fail toward preservation)."""
        try:
            data = json.loads(self.env.hold_path.read_bytes().decode("utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return None
        until = str(data.get("hold_until", "")).strip()
        if not until:
            return None
        return RetentionHold(hold_until=until, note=str(data.get("note", "")))

    def write_hold(self, hold_until: str, note: str = "") -> RetentionHold:
        """Set or replace the hold. The turn-3 surfaces' write path."""
        hold = RetentionHold(hold_until=hold_until, note=note)
        self.env.hold_path.parent.mkdir(parents=True, exist_ok=True)
        self.env.hold_path.write_bytes(
            (
                json.dumps(
                    {
                        "hold_until": hold.hold_until,
                        "note": hold.note,
                        "set_on": self.env.today,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        )
        return hold

    # ── plan ─────────────────────────────────────────────────────────────

    def build_plan(self) -> UninstallPlan:
        """Scan the roots, the ledger, the discovery list and the registry.

        Read-only: a plan never stops, moves, or deletes anything (dry-run
        is build_plan + render).
        """
        env = self.env
        warnings: list[str] = []
        ledger = FootprintLedger(env.ledger_path).load()
        discovery_mode = not ledger.exists
        if discovery_mode:
            warnings.append(
                "no footprint ledger found — discovery mode: locations are "
                "inferred, and anything shared or pre-existing is never removed"
            )

        items: list[PlanItem] = []
        if env.data_root.exists():
            items.append(PlanItem(env.data_root, GROUP_AA, self._tree_size(env.data_root), note="AA data home"))

        if env.install_root is not None and env.install_root.exists():
            if env.run_mode in ("portable-frozen", "managed"):
                items.append(
                    PlanItem(env.install_root, GROUP_INSTALL, self._tree_size(env.install_root), note="AA runtime (frozen) — removed after exit")
                )
            elif not is_within(env.install_root, env.data_root, realpath=env.realpath) and env.install_root != env.data_root:
                warnings.append(
                    f"install root {env.install_root} is a {env.run_mode} install — left for your own tools"
                )

        # A source checkout registered via --install --source is pre-existing:
        # shown in the plan, never deleted.
        if env.install_root is not None:
            manifest = load_manifest(env.install_root)
            if (
                manifest is not None
                and manifest.project_dir is not None
                and manifest.project_origin == "preexisting"
                and manifest.project_dir.exists()
            ):
                items.append(
                    PlanItem(
                        manifest.project_dir,
                        GROUP_PREEXISTING,
                        0,
                        origin="preexisting",
                        note="source checkout registered at install time — not AA's",
                    )
                )

        for outside in ledger.outside:
            if not outside.path.exists() and not outside.path.is_symlink():
                continue
            group = GROUP_AA if outside.origin == "aa" else GROUP_PREEXISTING
            items.append(
                PlanItem(outside.path, group, self._tree_size(outside.path), origin=outside.origin, note=outside.note)
            )

        for path, origin, note in self._discovery_candidates():
            if any(self._same(path, i.path) for i in items):
                continue
            if is_within(path, env.data_root, realpath=env.realpath):
                continue
            if path.exists():
                items.append(
                    PlanItem(
                        path,
                        GROUP_AA if origin == "aa" else GROUP_PREEXISTING,
                        self._tree_size(path) if origin == "aa" else 0,
                        origin=origin,
                        note=note,
                    )
                )

        research_items = [
            PlanItem(p, GROUP_RESEARCH, self._tree_size(p)) for p in self._research_top_level()
        ]
        running = [
            rec.pid
            for rec in InstanceRegistry(env.instances_dir).alive()
            if rec.pid != os.getpid()
        ]
        hold = self.read_hold()
        if hold is not None and not hold.active(env.today):
            hold = None  # expired — treated as absent
        return UninstallPlan(
            run_mode=env.run_mode,
            data_root=env.data_root,
            install_root=env.install_root,
            items=items,
            research_items=research_items,
            running_pids=running,
            hold=hold,
            discovery_mode=discovery_mode,
            warnings=warnings,
        )

    def _discovery_candidates(self) -> list[tuple[Path, str, str]]:
        """Known locations outside the data root. "aa" = AA certainly created
        it (it was AA's own mkdir); "unknown" = possibly shared — reported,
        never removed."""
        home = self.env.home
        candidates: list[tuple[Path, str, str]] = [
            (home / ".auto_apply" / "gecko-profile-root", "aa", "legacy geckodriver profile root (pre-lifecycle AA)"),
            (home / ".cache" / "selenium", "unknown", "Selenium Manager driver cache (possibly shared)"),
        ]
        if sys.platform == "darwin":
            candidates.append((home / "Library" / "Caches" / "ms-playwright", "unknown", "Playwright browsers (possibly shared)"))
        elif os.name == "nt":
            local = os.environ.get("LOCALAPPDATA")
            if local:
                candidates.append((Path(local) / "ms-playwright", "unknown", "Playwright browsers (possibly shared)"))
        else:
            candidates.append((home / ".cache" / "ms-playwright", "unknown", "Playwright browsers (possibly shared)"))
        candidates.append((home / ".cache" / "huggingface", "unknown", "Hugging Face cache (possibly shared)"))
        candidates.append((home / ".cache" / "gpt4all", "unknown", "GPT4All models (possibly shared)"))
        return candidates

    def _research_top_level(self) -> list[Path]:
        """The research data home as top-level paths (research_db and
        page_copies live inside research_dir; they move with it)."""
        env = self.env
        candidates = [
            env.research_dir,
            env.research_db,
            env.consent_db,
            env.provenance_key,
            env.research_salt,
            env.hold_path,
        ]
        existing: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            if path.is_dir() and not path.is_symlink() and not any(
                f.is_file() or f.is_symlink() for f in path.rglob("*")
            ):
                # An EMPTY research folder (config creates it for every
                # install) is not research data: counting it kept every
                # default uninstall from removing the data home.
                continue
            if path.exists() or path.is_symlink():
                existing.append(path)
        return [
            p
            for p in existing
            if not any(p != other and is_within(p, other, realpath=env.realpath) for other in existing)
        ]

    @staticmethod
    def _same(a: Path, b: Path) -> bool:
        return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))

    @staticmethod
    def _tree_size(path: Path) -> int:
        try:
            if path.is_symlink() or not path.is_dir():
                return path.lstat().st_size if path.exists() or path.is_symlink() else 0
            total = 0
            for root, _dirs, files in os.walk(path):
                for name in files:
                    try:
                        total += (Path(root) / name).lstat().st_size
                    except OSError:
                        pass
            return total
        except OSError:
            return 0

    # ── execute ──────────────────────────────────────────────────────────

    def execute(
        self, plan: UninstallPlan, decision: UninstallDecision, *, dry_run: bool = False
    ) -> UninstallReport:
        """Stop, protect research, delete, finish, verify. See module docstring."""
        report = UninstallReport(run_mode=plan.run_mode, dry_run=dry_run)
        if dry_run:
            return report
        if not decision.confirm:
            raise UninstallRefused("uninstall was not confirmed")
        action = self._effective_action(plan, decision.research)

        self._note("stopping the research observer")
        self._stop_research_observer(report)
        self._note("stopping AA processes and AA-launched browsers")
        self._stop_processes(plan, report)
        self._note("handling research data")
        protected = self._research_step(plan, action, decision, report)
        self._note("removing AutoApply's files")
        roots = self._permitted_roots(plan)
        for item in plan.items:
            if item.group == GROUP_PREEXISTING:
                report.kept.append(Leftover(str(item.path), "existed before AA / possibly shared — not touched"))
                continue
            if item.group == GROUP_INSTALL:
                continue  # handed to the finisher below
            try:
                if self._same(item.path, self.env.data_root):
                    self._remove_data_root(protected, roots, report)
                else:
                    guarded_remove(item.path, roots, realpath=self.env.realpath)
                    report.removed.append(str(item.path))
            except OutOfScopeError as exc:
                report.failed.append(Leftover(str(item.path), str(exc)))
            except OSError as exc:
                report.failed.append(Leftover(str(item.path), f"{type(exc).__name__}: {exc}"))

        # The finisher gets only entries AA can PROVE it created (D1,
        # measured: the user's own files in a frozen drive root went to the
        # finisher). Managed roots prove entries via the receipt; frozen via
        # the two-entry known set; the root itself is a target only for a
        # managed root with its manifest and nothing excluded — a frozen
        # root is the user's folder or drive and is never a target.
        install_targets: list[Path] = []
        protected_resolved = {Path(self.env.realpath(str(p))) for p in protected}

        def _conflicts_with_protected(resolved: Path) -> bool:
            return any(
                prot == resolved
                or resolved in prot.parents  # contains a protected path
                or prot in resolved.parents  # inside a protected path
                for prot in protected_resolved
            )

        for item in plan.items:
            if item.group != GROUP_INSTALL or not item.path.exists():
                continue
            known = self._install_root_known_entries(item.path, plan.run_mode)
            excluded_any = False
            for child in sorted(item.path.iterdir()):
                resolved = Path(self.env.realpath(str(child)))
                if _conflicts_with_protected(resolved):
                    excluded_any = True
                    report.kept.append(Leftover(str(child), "research data kept in place"))
                    continue
                if child.name not in known:
                    excluded_any = True
                    report.kept.append(Leftover(str(child), "not AA's — left in place"))
                    continue
                install_targets.append(child)
            if (
                not excluded_any
                and plan.run_mode == "managed"
                and (item.path / "install.json").exists()
            ):
                install_targets.append(item.path)  # last: removes the emptied root too
        if install_targets:
            staging = launch_detached(install_targets, tuple(install_targets))
            report.kept.append(
                Leftover(
                    ", ".join(str(p) for p in install_targets),
                    "runtime removal handed to the detached finisher "
                    f"(staging: {staging}). It runs after AutoApply exits and "
                    "writes aa_uninstall_result.json there ONLY if something "
                    "could not be removed — no result file means a clean "
                    "finish. Re-run --uninstall --dry-run to confirm.",
                )
            )

        self._note("verifying")
        self._verify(plan, report)
        return report

    def _note(self, message: str) -> None:
        """Progress for the surfaces (CLI stderr lines, GUI status label).

        Injected, never printed here: an application service does not choose
        a stream or a widget."""
        if self.env.progress is not None:
            self.env.progress(message)

    def _effective_action(self, plan: UninstallPlan, research) -> str:
        """Resolve and VALIDATE the research action before anything stops.

        A retention hold refuses destruction — keep (a move) and export (a
        copy) preserve the records and remain available; delete is refused
        no matter what flags accompanied it.
        """
        action = research.action
        hold = plan.hold
        if hold is not None and action == "delete":
            raise UninstallRefused(
                f"a research retention hold is active on this device (until "
                f"{hold.hold_until}{': ' + hold.note if hold.note else ''}). "
                "Research records cannot be destroyed while it holds. "
                "Offered instead: --research-export DIR."
            )
        if action is None:
            return "keep-in-place"
        if action in ("keep", "export"):
            if research.dest is None:
                raise UninstallRefused(f"--research-{action} needs a destination directory")
            self._validate_dest(research.dest)
            return action
        if action in ("delete", "keep-in-place"):
            return action
        raise UninstallRefused(f"unknown research action {action!r}")

    def _validate_dest(self, dest: Path) -> None:
        resolved = Path(self.env.realpath(str(dest)))
        data = Path(self.env.realpath(str(self.env.data_root)))
        if (
            resolved == data
            or is_within(resolved, data, realpath=self.env.realpath)
            or is_within(data, resolved, realpath=self.env.realpath)
        ):
            raise UninstallRefused(
                "the destination must not be inside — or contain — the data home"
            )

    def _permitted_roots(self, plan: UninstallPlan) -> tuple[Path, ...]:
        """The data root, the install root (when slated), and each ledgered
        AA-created item outside the roots — deletable exactly there and
        nowhere else."""
        roots: list[Path] = [self.env.data_root]
        for item in plan.items:
            if item.group == GROUP_INSTALL:
                roots.append(item.path)
            elif item.group == GROUP_AA and not is_within(
                item.path, self.env.data_root, realpath=self.env.realpath
            ):
                roots.append(item.path)
        return tuple(roots)

    # ── stop first ───────────────────────────────────────────────────────

    def _consent_manager(self) -> Any:
        if self._manager is not None:
            return self._manager
        if self.env.consent_factory is None or not self.env.consent_db.exists():
            return None
        self._manager = self.env.consent_factory()
        return self._manager

    def _stop_research_observer(self, report: UninstallReport) -> None:
        """Stop this process's observer BEFORE any purge or move — the
        measured failure was a live aggregator recreating the database and
        minting a new key after a purge."""
        manager = self._consent_manager()
        if manager is not None:
            manager.stop_collection()  # process-wide channel (the S2 fix)

    def _stop_processes(self, plan: UninstallPlan, report: UninstallReport) -> None:
        for pid in plan.running_pids:
            self._terminate_pid(pid, report)
        for pid in self._aa_browser_pids():
            self._terminate_pid(pid, report)

    def _terminate_pid(self, pid: int, report: UninstallReport) -> None:
        if pid == os.getpid():
            return
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            report.stopped_pids.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass

    _CHROMIUM_PROFILE_FLAG = "--user-data-dir"
    _FIREFOX_PROFILE_FLAG = "-profile"

    def _aa_browser_pids(self) -> list[int]:
        """Browsers launched BY AA: an argument that IS the profile flag
        with AA's profile dir as its exact value.

        Never a substring match (D5, measured): an editor or file manager
        with the folder open carries the same string and would be killed.
        AA's own processes go through the registry's pid+start-time check
        instead, which is unaffected.
        """
        marker = os.path.normcase(os.path.normpath(str(self.env.browser_profile_dir)))
        if not marker:
            return []
        scan = self.env.processes or psutil.process_iter
        found: list[int] = []
        for proc in scan(attrs=["pid", "cmdline"]):
            try:
                pid = int(proc.info["pid"])
                args = [str(a) for a in (proc.info.get("cmdline") or [])]
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, KeyError):
                continue
            if pid == os.getpid():
                continue
            for index, arg in enumerate(args):
                if arg.startswith(self._CHROMIUM_PROFILE_FLAG + "="):
                    value = arg.split("=", 1)[1]
                    if os.path.normcase(os.path.normpath(value)) == marker:
                        found.append(pid)
                        break
                elif (
                    arg in (self._CHROMIUM_PROFILE_FLAG, self._FIREFOX_PROFILE_FLAG)
                    and index + 1 < len(args)
                    and os.path.normcase(os.path.normpath(args[index + 1])) == marker
                ):
                    found.append(pid)
                    break
        return found

    # ── the research-data step ───────────────────────────────────────────

    def _research_step(
        self, plan: UninstallPlan, action: str, decision: UninstallDecision, report: UninstallReport
    ) -> set[Path]:
        """Returns the protected set: paths excluded from deletion."""
        if not plan.research_items:
            report.research_action = "none-present"
            return set()
        manager = self._consent_manager()
        hold = plan.hold
        # Page copies follow their own consent text (deleted on withdrawal)
        # UNLESS a hold is active — then nothing research-related is destroyed.
        purge_copies = hold is None

        if action == "keep-in-place":
            if hold is not None and manager is not None:
                manager.withdraw_consent(purge_data=False, purge_copies=False)
                notice = self._write_notice(self.env.research_dir, method="uninstall (retention hold)")
                report.withdrawals_documented_at = str(notice)
                report.research_detail = (
                    f"research data left untouched (retention hold until {hold.hold_until})"
                )
            else:
                report.research_detail = "research data left untouched (default — no choice made)"
            report.research_action = "keep-in-place"
            return set(self._research_top_level())

        if action == "keep":
            dest = decision.research.dest
            assert dest is not None  # validated in _effective_action
            if manager is not None:
                manager.withdraw_consent(purge_data=False, purge_copies=purge_copies)
            self._move_research_home(dest, report)
            notice = self._write_notice(dest, method="uninstall (kept)")
            report.research_action = "keep"
            report.research_detail = f"research data home moved to {dest}"
            report.withdrawals_documented_at = str(notice)
            return set()

        if action == "export":
            dest = decision.research.dest
            assert dest is not None
            if self.env.export_bundle is None:
                raise UninstallRefused("no exporter is wired for --research-export")
            if manager is not None:
                manager.withdraw_consent(purge_data=False, purge_copies=purge_copies)
            result = self.env.export_bundle(dest, decision.research.fmt)
            bundle_dir = Path(getattr(result, "directory", dest))
            if self.env.verify_bundle is not None:
                self.env.verify_bundle(bundle_dir)
            notice = self._write_notice(bundle_dir, method="uninstall (exported)")
            report.research_action = "export"
            report.research_detail = (
                f"verified bundle at {bundle_dir}; originals removed with the data home"
            )
            report.withdrawals_documented_at = str(notice)
            return set()

        # action == "delete" — a hold was already refused in _effective_action.
        if manager is None:
            raise UninstallRefused("no consent manager available for the purge path")
        manager.withdraw(purge_data=True)
        report.research_action = "delete"
        report.research_detail = "research data securely purged via the consent withdrawal path"
        return set()

    def _move_research_home(self, dest: Path, report: UninstallReport) -> None:
        """Move every top-level research path to dest. Copy-verify-delete:
        a source is removed only after its copy checks out."""
        if dest.exists() and any(dest.iterdir()):
            raise UninstallRefused(f"destination is not empty: {dest}")
        dest.mkdir(parents=True, exist_ok=True)
        roots = (self.env.data_root,)
        for src in self._research_top_level():
            target = dest / src.name
            try:
                os.rename(src, target)
                continue
            except OSError:
                pass  # cross-device: copy, verify, then delete the source
            if src.is_dir() and not src.is_symlink():
                shutil.copytree(src, target)
                self._verify_copy(src, target)
            else:
                shutil.copy2(src, target)
                if target.stat().st_size != src.stat().st_size:
                    raise UninstallRefused(f"move verification failed for {src}")
            guarded_remove(src, roots, realpath=self.env.realpath)

    @staticmethod
    def _verify_copy(src: Path, target: Path) -> None:
        def _stats(root: Path) -> tuple[int, int]:
            files = [p for p in root.rglob("*") if p.is_file()]
            return len(files), sum(p.stat().st_size for p in files)

        if _stats(src) != _stats(target):
            raise UninstallRefused(f"move verification failed for {src}")

    def _write_notice(self, directory: Path, *, method: str) -> Path:
        """The OHRP-aligned withdrawal record: who decided, the scope — and
        nothing identifying. Written only into data that SURVIVES the
        uninstall."""
        payload = {
            "type": "research-withdrawal-notice",
            "date": self.env.today,
            "decided_by": "subject",
            "scope": "all research components",
            "method": method,
            "identifying_information": "none",
        }
        target = Path(directory) / WITHDRAWAL_NOTICE_FILENAME
        target.write_bytes(
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        return target

    # ── deletion ─────────────────────────────────────────────────────────

    def _data_root_known_entries(self) -> frozenset[str]:
        env = self.env
        derived = {
            env.ledger_path.name,
            env.instances_dir.name,
            env.research_dir.name,
            env.research_db.name,
            env.consent_db.name,
            env.provenance_key.name,
            env.research_salt.name,
            env.hold_path.name,
        }
        return DATA_ROOT_KNOWN_ENTRIES | derived

    def _install_root_known_entries(self, root: Path, run_mode: str) -> frozenset[str]:
        """The entries AA may remove from an install root (D1).

        Managed: the receipt --install wrote (the constant it is written
        from is the fallback for roots installed before receipts existed —
        the requirement-(c) discovery answer, conservative by construction).
        Frozen: the build's own two entries.
        """
        if run_mode == "managed":
            receipt = root / RECEIPT_NAME
            try:
                data = json.loads(receipt.read_bytes().decode("utf-8"))
                return frozenset(str(e) for e in data["entries"])
            except (OSError, ValueError, KeyError, TypeError):
                return frozenset(MANAGED_RECEIPT_ENTRIES)
        return FROZEN_KNOWN_ENTRIES

    def _remove_data_root(
        self, protected: set[Path], roots: tuple[Path, ...], report: UninstallReport
    ) -> None:
        root = self.env.data_root
        resolved_protected = {Path(self.env.realpath(str(p))) for p in protected}

        def _is_protected(p: Path) -> bool:
            rp = Path(self.env.realpath(str(p)))
            return rp in resolved_protected or any(
                parent in resolved_protected for parent in rp.parents
            )

        if not root.exists():
            return
        created_by_aa = (root / CREATION_MARKER_NAME).exists()
        known = self._data_root_known_entries()
        for child in sorted(root.iterdir()):
            if child.name == CREATION_MARKER_NAME:
                # The ownership proof goes LAST, below: deleted first (it
                # sorts first), an interrupted run lost it and the next run
                # then left the whole folder as "existed before AA".
                continue
            if _is_protected(child):
                report.kept.append(Leftover(str(child), "research data kept in place"))
                continue
            if child.name not in known:
                # Rule (a): delete only what AA can show it created (D2).
                report.kept.append(Leftover(str(child), "not AA's — left in place"))
                continue
            try:
                guarded_remove(child, roots, realpath=self.env.realpath)
                report.removed.append(str(child))
            except (OutOfScopeError, OSError) as exc:
                report.failed.append(Leftover(str(child), f"{type(exc).__name__}: {exc}"))
        if not created_by_aa:
            # Rule (b): a root is removed wholesale only if AA created it.
            report.kept.append(
                Leftover(str(root), "this folder existed before AA — left in place")
            )
            return
        if any(c.name != CREATION_MARKER_NAME for c in root.iterdir()):
            return  # kept or failed items remain; the marker stays for the next run
        try:
            (root / CREATION_MARKER_NAME).unlink(missing_ok=True)
            root.rmdir()
            report.removed.append(str(root))
        except OSError:
            pass  # verify reports what is still there

    # ── verify ───────────────────────────────────────────────────────────

    def _verify(self, plan: UninstallPlan, report: UninstallReport) -> None:
        """Re-scan everything the plan named. Anything still present that was
        not intentionally kept, already recorded as failed, or handed to the
        finisher is an unexpected leftover — reported, never hidden."""
        intentional = {k.path for k in report.kept} | {f.path for f in report.failed}
        for item in [*plan.items, *plan.research_items]:
            if item.group == GROUP_INSTALL:
                continue  # async — the detached finisher owns these
            path = item.path
            if not path.exists() and not path.is_symlink():
                continue
            if str(path) in intentional:
                continue
            if self._same(path, self.env.data_root) and (
                report.research_action == "keep-in-place" or report.failed
            ):
                report.kept.append(
                    Leftover(str(path), "not empty after uninstall — see kept/failed items")
                )
                continue
            report.leftovers.append(Leftover(str(path), "still present after uninstall"))
