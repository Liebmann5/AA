"""The GUI query-builder window (File → Build a Search…).

The second builder surface; the CLI search screen is the first, and parity is
pinned: both read their offers through the same builder method names — the UI
port's builder methods, resolve_query_target included — and render results
through the same domain helpers (domain/models/search_query.py). Every
testable rule lives in the widget-free helpers below, so no pin constructs Tk
(the research_window.py precedent).

Rules this window exists to keep:

    * Preview never writes to the device. Copy, open and keep are the only
      actions that remember a query, and platform/company queries are
      remembered resolved, so they replay identically from either surface.
    * The only outward call is webbrowser.open, on an explicit click. Nothing
      else touches the network.
    * A refusal renders in plain words, never a blank result.
    * Accessibility (WCAG 2.1 AA): every control is labelled and reachable by
      keyboard; copy, keep and refusal outcomes are announced as text in the
      status line, not by colour alone; Escape and the window-close button
      decline without remembering anything.

What the source-level pins CANNOT check headless: real Tab traversal and
screen-reader behaviour. The guarantees above are structural; the rest is
manual testing, said plainly.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from collections.abc import Callable
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from auto_apply.domain.models.search_query import (
    build_request,
    describe_request,
    format_result_lines,
    platform_display_text,
    resolve_and_remember,
)

__all__ = [
    "SearchBuilderWindow",
    "TARGET_KINDS",
    "build_for_target",
    "offered_input_fields",
    "offered_option_choices",
    "platform_choices",
    "recent_choices",
    "result_lines",
    "surface_choices",
]

#: The three search targets, in display order. Labels come from the locale at
#: render time; these keys never change.
TARGET_KINDS = ("surface", "platform", "company")


def surface_choices(offers) -> list[tuple[str, str]]:
    """(name, display name) pairs for the engine combobox."""
    return [(o.name, o.display_name) for o in offers]


def platform_choices(offers) -> list[tuple[str, str]]:
    """(name, label) pairs; the label is the service's shared verification label."""
    return [(o.name, platform_display_text(o)) for o in offers]


def offered_input_fields(offer) -> frozenset[str]:
    """The operator keys a surface offers, driving which optional fields show."""
    if offer is None:
        return frozenset()
    return frozenset(op.key for op in offer.operators)


def offered_option_choices(offer) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(key, label, [(choice key, choice label)]) for a surface's URL options."""
    if offer is None:
        return []
    return [
        (opt.key, opt.label, [(c.key, c.label) for c in opt.choices])
        for opt in offer.options
    ]


def build_for_target(builder, request, *, platform=None, company_url=None):
    """The one dispatch the preview and every action share — the same three
    branches the CLI takes."""
    if platform:
        return builder.build_platform_query(platform, request)
    if company_url:
        return builder.build_company_query(company_url, request)
    return builder.build_query(request)


def result_lines(result, translate) -> list[str]:
    """The result as display lines — the same domain helper the CLI uses."""
    return format_result_lines(result, translate=translate)


def recent_choices(recent) -> list[str]:
    """One line per remembered query, for the recent combobox."""
    return [describe_request(r) for r in recent]


class SearchBuilderWindow(tk.Toplevel):
    """The window. Wires widgets to the helpers above; owns no policy."""

    def __init__(
        self,
        parent: tk.Misc,
        builder: Any,
        *,
        translate: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._builder = builder
        self._t = translate if translate is not None else (lambda key: key)
        self._last_result = None
        self._last_request = None
        self._last_platform = None
        self._last_company_url = None
        self._recent: tuple = ()

        self._surfaces = tuple(builder.query_surfaces())
        self._platforms = tuple(builder.query_platforms())
        self._defaults = builder.query_defaults()
        self._engine_names = [n for n, _ in surface_choices(self._surfaces)]
        self._engine_display = [d for _, d in surface_choices(self._surfaces)]
        self._platform_names = [n for n, _ in platform_choices(self._platforms)]
        self._platform_display = [d for _, d in platform_choices(self._platforms)]

        self._engine_var = tk.StringVar()
        self._target_var = tk.StringVar(value="surface")
        self._platform_var = tk.StringVar()
        self._company_var = tk.StringVar()
        self._terms_var = tk.StringVar()
        self._location_var = tk.StringVar()
        self._anyof_var = tk.StringVar()
        self._exclude_var = tk.StringVar()
        self._intitle_var = tk.StringVar()
        self._recent_var = tk.StringVar()
        self._status_var = tk.StringVar()
        self._option_vars: dict[str, tk.StringVar] = {}
        self._option_choice_maps: dict[str, dict[str, str]] = {}
        self._operator_rows: dict[str, ttk.Frame] = {}

        self.title(self._t("builder.window_title"))
        self.geometry("780x720")
        self.minsize(640, 540)
        self.transient(parent)  # type: ignore[call-overload]
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _event: self._close())

        self._build_widgets()
        self._prefill_defaults()
        if self._engine_display:
            self._engine_box.current(0)
        self._on_engine_change()
        self._refresh_recent()

    # ── layout ──────────────────────────────────────────────────────────

    def _labelled_entry(self, parent, key: str, var) -> ttk.Frame:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=self._t(key)).pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=var, width=52)
        entry.pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)
        var.trace_add("write", lambda *_: self._on_change())
        return row

    def _quick_pick(self, parent, values, var) -> None:
        box = ttk.Combobox(parent, values=values, state="readonly", width=26)
        box.set(self._t("builder.pick_one"))
        box.pack(side=tk.LEFT, padx=(6, 0))

        def _apply(_event=None) -> None:
            var.set(box.get())
            self._on_change()

        box.bind("<<ComboboxSelected>>", _apply)

    def _build_widgets(self) -> None:
        # The button row packs side=BOTTOM BEFORE the expanding content so it
        # reserves its height — the Settings dialog's load-bearing lesson.
        buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        buttons.pack(fill=tk.X, side=tk.BOTTOM)
        self._copy_text_btn = ttk.Button(buttons, text=self._t("builder.copy_text"), command=self._copy_text)
        self._copy_link_btn = ttk.Button(buttons, text=self._t("builder.copy_link"), command=self._copy_link)
        self._open_link_btn = ttk.Button(buttons, text=self._t("builder.open_link"), command=self._open_link)
        self._keep_btn = ttk.Button(buttons, text=self._t("builder.keep"), command=self._keep)
        for button in (self._copy_text_btn, self._copy_link_btn, self._open_link_btn, self._keep_btn):
            button.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text=self._t("builder.close"), command=self._close).pack(side=tk.RIGHT)

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        row = ttk.Frame(outer)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=self._t("builder.engine_label")).pack(side=tk.LEFT)
        self._engine_box = ttk.Combobox(
            row, textvariable=self._engine_var,
            values=self._engine_display, state="readonly", width=30,
        )
        self._engine_box.pack(side=tk.LEFT, padx=(8, 0))
        self._engine_box.bind("<<ComboboxSelected>>", self._on_engine_change)

        row = ttk.Frame(outer)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=self._t("builder.target_label")).pack(side=tk.LEFT)
        for kind in TARGET_KINDS:
            ttk.Radiobutton(
                row,
                text=self._t(f"builder.target.{kind}"),
                value=kind,
                variable=self._target_var,
                command=self._on_target_change,
            ).pack(side=tk.LEFT, padx=(8, 0))

        self._platform_row = ttk.Frame(outer)
        ttk.Label(self._platform_row, text=self._t("builder.platform_label")).pack(side=tk.LEFT)
        self._platform_box = ttk.Combobox(
            self._platform_row, textvariable=self._platform_var,
            values=self._platform_display, state="readonly", width=44,
        )
        self._platform_box.pack(side=tk.LEFT, padx=(8, 0))
        self._platform_box.bind("<<ComboboxSelected>>", lambda _e: self._on_change())

        self._company_row = ttk.Frame(outer)
        ttk.Label(self._company_row, text=self._t("builder.company_label")).pack(side=tk.LEFT)
        ttk.Entry(self._company_row, textvariable=self._company_var, width=52).pack(
            side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True
        )
        self._company_var.trace_add("write", lambda *_: self._on_change())

        self._labelled_entry(outer, "builder.terms_label", self._terms_var)
        self._labelled_entry(outer, "builder.location_label", self._location_var)

        if self._defaults and (self._defaults.titles or self._defaults.locations):
            picks = ttk.Frame(outer)
            picks.pack(fill=tk.X, pady=2)
            ttk.Label(picks, text=self._t("builder.defaults_label")).pack(side=tk.LEFT)
            if self._defaults.titles:
                self._quick_pick(picks, list(self._defaults.titles), self._terms_var)
            if self._defaults.locations:
                self._quick_pick(picks, list(self._defaults.locations), self._location_var)

        self._operator_rows["any_of"] = self._labelled_entry(outer, "builder.any_of_label", self._anyof_var)
        self._operator_rows["exclude"] = self._labelled_entry(outer, "builder.exclude_label", self._exclude_var)
        self._operator_rows["intitle"] = self._labelled_entry(outer, "builder.in_title_label", self._intitle_var)

        self._options_frame = ttk.Frame(outer)
        self._options_frame.pack(fill=tk.X)

        ttk.Label(outer, text=self._t("builder.preview_label")).pack(anchor=tk.W, pady=(8, 0))
        self._preview = ScrolledText(outer, height=12, wrap=tk.WORD, state="disabled", takefocus=True)
        self._preview.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        recent_row = ttk.Frame(outer)
        recent_row.pack(fill=tk.X, pady=2)
        ttk.Label(recent_row, text=self._t("builder.recent_label")).pack(side=tk.LEFT)
        self._recent_box = ttk.Combobox(recent_row, textvariable=self._recent_var, state="readonly", width=46)
        self._recent_box.pack(side=tk.LEFT, padx=(8, 0))
        self._recent_box.bind("<<ComboboxSelected>>", self._on_recent_selected)
        ttk.Button(recent_row, text=self._t("builder.clear_recent"), command=self._clear_recent).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(outer, textvariable=self._status_var, wraplength=720).pack(anchor=tk.W, pady=(4, 0))

    # ── offers / visibility ───────────────────────────────────────────────

    def _current_engine_name(self) -> str:
        idx = self._engine_box.current()
        if 0 <= idx < len(self._engine_names):
            return self._engine_names[idx]
        return self._engine_names[0] if self._engine_names else ""

    def _current_offer(self):
        name = self._current_engine_name()
        for offer in self._surfaces:
            if offer.name == name:
                return offer
        return None

    def _rebuild_options(self) -> None:
        for child in self._options_frame.winfo_children():
            child.destroy()
        self._option_vars = {}
        self._option_choice_maps = {}
        choices = offered_option_choices(self._current_offer())
        if not choices:
            return
        ttk.Label(self._options_frame, text=self._t("builder.options_label")).pack(anchor=tk.W)
        for key, label, opts in choices:
            row = ttk.Frame(self._options_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"{label}:").pack(side=tk.LEFT)
            if opts:
                not_set = self._t("builder.option_not_set")
                var = tk.StringVar(value=not_set)
                self._option_vars[key] = var
                self._option_choice_maps[key] = {c_label: c_key for c_key, c_label in opts}
                box = ttk.Combobox(
                    row, textvariable=var, state="readonly", width=26,
                    values=[not_set] + [c_label for _, c_label in opts],
                )
                box.pack(side=tk.LEFT, padx=(8, 0))
                box.bind("<<ComboboxSelected>>", lambda _e: self._on_change())
            else:
                var = tk.StringVar()
                self._option_vars[key] = var
                ttk.Entry(row, textvariable=var, width=28).pack(side=tk.LEFT, padx=(8, 0))
                var.trace_add("write", lambda *_: self._on_change())

    def _refresh_field_visibility(self) -> None:
        supported = offered_input_fields(self._current_offer())
        for key, row in self._operator_rows.items():
            if key in supported:
                row.pack(fill=tk.X, pady=2)
            else:
                row.pack_forget()

    def _prefill_defaults(self) -> None:
        if self._defaults is not None:
            if self._defaults.titles:
                self._terms_var.set(", ".join(self._defaults.titles))
            if self._defaults.locations:
                self._location_var.set(self._defaults.locations[0])

    # ── building ──────────────────────────────────────────────────────────

    def _on_engine_change(self, _event=None) -> None:
        self._rebuild_options()
        self._refresh_field_visibility()
        self._on_change()

    def _on_target_change(self) -> None:
        kind = self._target_var.get()
        self._platform_row.pack_forget()
        self._company_row.pack_forget()
        if kind == "platform":
            self._platform_row.pack(fill=tk.X, pady=2)
            if self._platform_display and self._platform_box.current() < 0:
                self._platform_box.current(0)
        elif kind == "company":
            self._company_row.pack(fill=tk.X, pady=2)
        self._on_change()

    def _current_options(self) -> tuple[tuple[str, str], ...]:
        out: list[tuple[str, str]] = []
        not_set = self._t("builder.option_not_set")
        for key, var in self._option_vars.items():
            value = var.get().strip()
            if not value or value == not_set:
                continue
            choice_map = self._option_choice_maps.get(key)
            if choice_map is not None:
                choice_key = choice_map.get(value)
                if choice_key is not None:
                    out.append((key, choice_key))
            else:
                out.append((key, value))
        return tuple(out)

    def _current_request(self):
        engine = self._current_engine_name()
        if not engine:
            return None
        return build_request(
            surface=engine,
            terms=self._terms_var.get(),
            any_of=self._anyof_var.get(),
            exclude=self._exclude_var.get(),
            in_title=self._intitle_var.get(),
            location=self._location_var.get(),
            options=self._current_options(),
        )

    def _target_args(self) -> tuple[str | None, str | None]:
        kind = self._target_var.get()
        if kind == "platform":
            idx = self._platform_box.current()
            if 0 <= idx < len(self._platform_names):
                return self._platform_names[idx], None
            return None, None
        if kind == "company":
            url = self._company_var.get().strip()
            return (None, url) if url else (None, None)
        return None, None

    def _on_change(self, *_args) -> None:
        request = self._current_request()
        if request is None:
            self._show_lines([self._t("builder.nothing_built")])
            self._last_result = None
            self._update_action_buttons()
            return
        platform, company_url = self._target_args()
        try:
            result = build_for_target(
                self._builder, request, platform=platform, company_url=company_url
            )
        except Exception as exc:  # noqa: BLE001 — the builder's message is user-facing text
            self._show_lines([f"{self._t('builder.error')}: {exc}"])
            self._last_result = None
            self._update_action_buttons()
            return
        self._last_result = result
        self._last_request = request
        self._last_platform = platform
        self._last_company_url = company_url
        self._show_lines(result_lines(result, self._t))
        self._update_action_buttons()

    def _show_lines(self, lines: list[str]) -> None:
        self._preview.configure(state="normal")
        self._preview.delete("1.0", tk.END)
        self._preview.insert(tk.END, "\n".join(lines) if lines else self._t("builder.nothing_built"))
        self._preview.configure(state="disabled")

    def _update_action_buttons(self) -> None:
        result = self._last_result
        has_text = bool(result and result.bar_text)
        has_url = bool(result and result.url)
        self._copy_text_btn.state(["!disabled"] if has_text else ["disabled"])
        self._copy_link_btn.state(["!disabled"] if has_url else ["disabled"])
        self._open_link_btn.state(["!disabled"] if has_url else ["disabled"])
        self._keep_btn.state(["!disabled"] if (has_text or has_url) else ["disabled"])

    # ── actions (the only writes, and the only outward call) ─────────────

    def _copy_text(self) -> None:
        if not (self._last_result and self._last_result.bar_text):
            self._announce("builder.status.no_result")
            return
        self.clipboard_clear()
        self.clipboard_append(self._last_result.bar_text)
        self._remember_last()
        self._announce("builder.status.copied_text")

    def _copy_link(self) -> None:
        if not (self._last_result and self._last_result.url):
            self._announce("builder.status.no_result")
            return
        self.clipboard_clear()
        self.clipboard_append(self._last_result.url)
        self._remember_last()
        self._announce("builder.status.copied_link")

    def _open_link(self) -> None:
        if not (self._last_result and self._last_result.url):
            self._announce("builder.status.no_result")
            return
        webbrowser.open(self._last_result.url)
        self._remember_last()
        self._announce("builder.status.opened")

    def _keep(self) -> None:
        if not (self._last_result and (self._last_result.bar_text or self._last_result.url)):
            self._announce("builder.status.no_result")
            return
        self._remember_last()
        self._announce("builder.status.kept")

    def _remember_last(self) -> None:
        if self._last_request is None:
            return
        resolve_and_remember(
            self._builder,
            self._last_request,
            platform=self._last_platform,
            company_url=self._last_company_url,
        )
        self._refresh_recent()

    # ── recent ────────────────────────────────────────────────────────────

    def _refresh_recent(self) -> None:
        recent = tuple(self._builder.recent_queries())
        self._recent = recent
        lines = recent_choices(recent)
        self._recent_box.configure(values=lines)
        self._recent_var.set(
            self._t("builder.recent_placeholder") if lines else self._t("builder.recent_empty_label")
        )

    def _on_recent_selected(self, _event=None) -> None:
        idx = self._recent_box.current()
        if not (0 <= idx < len(self._recent)):
            return
        request = self._recent[idx]
        if request.surface not in self._engine_names:
            self._announce("builder.status.recent_unavailable")
            return
        try:
            result = self._builder.build_query(request)
        except Exception as exc:  # noqa: BLE001
            self._show_lines([f"{self._t('builder.error')}: {exc}"])
            return
        self._last_result = result
        self._last_request = request
        self._last_platform = None
        self._last_company_url = None
        self._show_lines(result_lines(result, self._t))
        self._update_action_buttons()
        self._announce("builder.status.recent_loaded")

    def _clear_recent(self) -> None:
        self._builder.clear_recent_queries()
        self._refresh_recent()
        self._announce("builder.status.cleared")

    # ── status / close ────────────────────────────────────────────────────

    def _announce(self, key: str) -> None:
        self._status_var.set(self._t(key))

    def _close(self) -> None:
        self.destroy()
