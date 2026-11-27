"""AA's scrollbars: one quiet look for every scrolling area in the GUI.

The default Tk scrollbars (ttk's clam theme, and the classic Tk scrollbar
inside ``ScrolledText``) draw raised arrow buttons and a heavy bevelled
thumb. AA's windows use one flat, slim style instead — a light trough, a
grey thumb that darkens under the pointer and while dragged, no arrow
buttons (the wheel, the keyboard and dragging still scroll). Nothing else
about AA's look changes.

The style is built from the clam theme's own trough and thumb elements,
copied under AA's names, so it looks the same whichever ttk theme is active
(clam, vista, aqua, default) — a plain colour change would be ignored by
themes that draw scrollbars natively. If the copy is not possible, the
theme's standard scrollbar is used: a look never stops a window opening.

Use ``styled_scrollbar(parent, ...)`` for a ttk scrollbar, and
``ScrolledText`` from here instead of ``tkinter.scrolledtext`` (same
interface).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Any, Literal

VERTICAL_STYLE = "AA.Vertical.TScrollbar"
HORIZONTAL_STYLE = "AA.Horizontal.TScrollbar"

#: Colours: trough, thumb, thumb under the pointer, thumb while dragged.
TROUGH = "#EEEEEE"
THUMB = "#C2C2C2"
THUMB_ACTIVE = "#A0A0A0"
THUMB_PRESSED = "#808080"
#: Width of a vertical bar (height of a horizontal one), in pixels.
THICKNESS = 11


def ensure_scrollbar_style(widget: tk.Misc) -> str | None:
    """Register AA's scrollbar styles on ``widget``'s Tk interpreter.

    Returns the vertical style name, or None when the style could not be
    built (the theme's own scrollbar is then used). Idempotent.
    """
    try:
        style = ttk.Style(widget)
        names = set(style.element_names())
        if "AA.Vscrollbar.trough" not in names:
            for orient, ttk_name in (("V", "Vertical"), ("H", "Horizontal")):
                for part in ("trough", "thumb"):
                    style.element_create(f"AA.{orient}scrollbar.{part}", "from", "clam",
                                         f"{ttk_name}.Scrollbar.{part}")
        # Tk's layout spec is nested lists and dicts; typeshed's _Layout
        # cannot express "children", hence Any.
        vertical: Any = [("AA.Vscrollbar.trough", {"sticky": "ns", "children": [
            ("AA.Vscrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})]
        horizontal: Any = [("AA.Hscrollbar.trough", {"sticky": "we", "children": [
            ("AA.Hscrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})]
        style.layout(VERTICAL_STYLE, vertical)
        style.layout(HORIZONTAL_STYLE, horizontal)
        for name in (VERTICAL_STYLE, HORIZONTAL_STYLE):
            style.configure(name, troughcolor=TROUGH, background=THUMB,
                            bordercolor=TROUGH, lightcolor=THUMB, darkcolor=THUMB,
                            gripcount=0, gripsize=0, relief="flat", borderwidth=0,
                            width=THICKNESS, arrowsize=THICKNESS)
            style.map(name,
                      background=[("pressed", THUMB_PRESSED), ("active", THUMB_ACTIVE)],
                      lightcolor=[("pressed", THUMB_PRESSED), ("active", THUMB_ACTIVE)],
                      darkcolor=[("pressed", THUMB_PRESSED), ("active", THUMB_ACTIVE)])
        return VERTICAL_STYLE
    except tk.TclError:
        return None


def styled_scrollbar(parent: tk.Misc, orient: Literal["horizontal", "vertical"] = "vertical",
                     **kw: Any) -> ttk.Scrollbar:
    """A ttk scrollbar in AA's style (the theme's own if the style fails)."""
    if ensure_scrollbar_style(parent) is not None:
        kw.setdefault("style", VERTICAL_STYLE if orient == tk.VERTICAL else HORIZONTAL_STYLE)
    return ttk.Scrollbar(parent, orient=orient, **kw)


class ScrolledText(scrolledtext.ScrolledText):
    """``tkinter.scrolledtext.ScrolledText`` with AA's scrollbar.

    Same interface: a Text widget whose geometry methods place the frame
    holding it and its scrollbar.
    """

    def __init__(self, master: tk.Misc | None = None, **kw: Any) -> None:
        super().__init__(master, **kw)
        old = self.vbar
        bar = styled_scrollbar(self.frame, "vertical", command=self.yview)
        old.destroy()
        # ScrolledText routes pack() to its frame, so the Text is re-packed
        # through tk.Text's own method (as the standard library does) to sit
        # left of the new bar.
        tk.Text.pack_forget(self)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        tk.Text.pack(self, side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vbar = bar  # type: ignore[assignment]
        self.configure(yscrollcommand=bar.set)


__all__ = ["HORIZONTAL_STYLE", "VERTICAL_STYLE", "ScrolledText", "ensure_scrollbar_style",
           "styled_scrollbar"]
