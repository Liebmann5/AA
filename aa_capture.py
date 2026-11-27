#!/usr/bin/env python3
"""aa_capture.py: save real pages for AA's page-comprehension work, one click each.

Put this in the AA repo ROOT (next to packages/), like aa_measure.py.

    python aa_capture.py                     # checklist: packages/auto_apply/dev_data/captures/checklist.yaml
    python aa_capture.py --checklist FILE    # any other checklist

It opens its OWN Chrome window (a fresh, signed-out profile, separate from your
other windows) and a small control window. Browse in that Chrome. When the page
matches an item on the checklist, tick the item (or items) and press Extract.

Each capture is saved under
    packages/auto_apply/dev_data/captures/<item id>/<UTC time>_<host>/
(dev_data/ is git-ignored, so nothing here is ever committed):
    page.html.gz           the rendered page (after scripts ran)
    frames/NN.html.gz      each first-level iframe's rendered page
    dom_pierced.json.gz    the whole DOM including shadow roots and frame documents
    screenshot.png         the whole page, top to bottom
    ax_tree.json.gz        the browser's accessibility tree
    aa_extraction.json.gz  AA's own extraction of the page (what AA "sees")
    meta.json              address, title, time, items, AA's page verdict, sizes

It captures the tab you are looking at: the one you last switched to in that
Chrome (a "Sign in with ..." pop-up counts while it is open). Tabs opened in the
background with "Open in new tab" are not captured until you switch to them.
After each capture the window shows the title and site that were saved; "Undo
last" removes that capture. Every capture is also listed in captures/index.tsv.

Rules: never sign in, and never type real personal details, in this browser.
Never press Submit on a real application.
"""

# ruff: noqa: T201, PLC0415  (a command-line tool: it prints, and imports late so it can re-run itself under .venv)

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "packages" / "auto_apply"
CAPTURES = PKG / "dev_data" / "captures"
TOOL_VERSION = "3"


def _venv_python() -> Path | None:
    for p in (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python3",
        ROOT / ".venv" / "bin" / "python",
    ):
        if p.is_file():
            return p
    return None


def _ensure_venv() -> None:
    """Re-run under AA's .venv if this interpreter cannot import AA's pieces."""
    try:
        import auto_apply  # noqa: F401
        import selenium  # noqa: F401
        import yaml  # noqa: F401
    except ImportError:
        venv = _venv_python()
        if venv is None or Path(sys.executable).resolve() == venv.resolve():
            sys.exit(
                "Cannot import selenium, yaml or auto_apply, and no .venv was found next to this script."
            )
        sys.exit(
            subprocess.call([str(venv), str(Path(__file__).resolve()), *sys.argv[1:]])
        )


def _find_chrome() -> str:
    candidates = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            )
    candidates += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    for c in candidates:
        if c.is_file():
            return str(c)
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("Google Chrome was not found. Install Chrome, or put it on PATH.")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _slug(text: str) -> str:
    return (
        re.sub(r"[^a-z0-9.-]+", "-", (text or "page").lower()).strip("-")[:60] or "page"
    )


def _gz_write(path: Path, data: str | bytes) -> int:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    path.write_bytes(gzip.compress(raw))
    return len(raw)


class Browser:
    """A normal Chrome with its own temporary profile, driven over its debugging port."""

    def __init__(self) -> None:
        from selenium import webdriver

        self.profile = tempfile.mkdtemp(prefix="aa_capture_profile_")
        port = self.port = _free_port()
        self.proc = subprocess.Popen(
            [
                _find_chrome(),
                f"--remote-debugging-port={port}",
                f"--user-data-dir={self.profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--new-window",
                "about:blank",
            ]
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.3)
        options = webdriver.ChromeOptions()
        options.debugger_address = f"127.0.0.1:{port}"
        self.driver = webdriver.Chrome(options=options)

    def _targets(self) -> list[dict]:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/json/list", timeout=5
        ) as r:
            tabs = json.load(r)
        return [
            t
            for t in tabs
            if t.get("type") == "page"
            and not t.get("url", "").startswith("devtools://")
        ]

    def active_tab(self) -> dict:
        """The tab the person is on: Chrome lists tabs most recently switched-to first.

        Read over the debugging port without switching tabs, because switching
        through WebDriver brings a tab to the front. Among the most recent, the
        first that is actually showing wins (with one Chrome window, exactly one tab is).
        """
        import websocket

        tabs = self._targets()
        if not tabs:
            raise RuntimeError("no open tab in the capture browser")
        for tab in tabs:
            try:
                ws = websocket.create_connection(
                    tab["webSocketDebuggerUrl"], timeout=3, suppress_origin=True
                )
                try:
                    ws.send(
                        json.dumps(
                            {
                                "id": 1,
                                "method": "Runtime.evaluate",
                                "params": {
                                    "expression": "document.visibilityState",
                                    "returnByValue": True,
                                },
                            }
                        )
                    )
                    while True:
                        msg = json.loads(ws.recv())
                        if msg.get("id") == 1:
                            break
                finally:
                    ws.close()
                if msg.get("result", {}).get("result", {}).get("value") == "visible":
                    return tab
            except Exception:  # noqa: BLE001 - a busy tab just is not chosen by visibility
                continue
        return tabs[0]

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - closing is best effort
            pass
        shutil.rmtree(self.profile, ignore_errors=True)


def capture(driver, folder: Path, items: list[dict], tab_id: str) -> dict:
    """Save everything about one tab (already chosen) into folder; return its meta."""
    from selenium.webdriver.common.by import By

    errors: list[str] = []
    handles = driver.window_handles
    driver.switch_to.window(
        tab_id
    )  # the tab already in front, so nothing visibly moves
    folder.mkdir(parents=True, exist_ok=False)
    url, title = driver.current_url, driver.title
    html = driver.execute_script("return document.documentElement.outerHTML") or ""
    sizes = {"page.html": _gz_write(folder / "page.html.gz", html)}

    frames = []
    try:
        elements = driver.find_elements(By.TAG_NAME, "iframe")[:30]
        if elements:
            (folder / "frames").mkdir()
        for i, frame in enumerate(elements):
            src = frame.get_attribute("src") or ""
            try:
                driver.switch_to.frame(frame)
                fhtml = (
                    driver.execute_script("return document.documentElement.outerHTML")
                    or ""
                )
                _gz_write(folder / "frames" / f"{i:02d}.html.gz", fhtml)
                frames.append(
                    {"index": i, "src": src, "bytes": len(fhtml.encode("utf-8"))}
                )
            except Exception as exc:  # noqa: BLE001 - cross-origin or detached frames
                frames.append({"index": i, "src": src, "error": type(exc).__name__})
            finally:
                driver.switch_to.default_content()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"frames: {exc!r}")

    try:
        shot = driver.execute_cdp_cmd(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}
        )
        (folder / "screenshot.png").write_bytes(base64.b64decode(shot["data"]))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"full-page screenshot: {exc!r}")
        try:
            (folder / "screenshot.png").write_bytes(driver.get_screenshot_as_png())
        except Exception as exc2:  # noqa: BLE001
            errors.append(f"screenshot: {exc2!r}")

    try:
        # Shadow roots (open and closed) and frame documents, which outerHTML misses.
        doc = driver.execute_cdp_cmd("DOM.getDocument", {"depth": -1, "pierce": True})
        sizes["dom_pierced.json"] = _gz_write(
            folder / "dom_pierced.json.gz", json.dumps(doc)
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pierced DOM: {exc!r}")

    try:
        ax = driver.execute_cdp_cmd("Accessibility.getFullAXTree", {})
        sizes["ax_tree.json"] = _gz_write(folder / "ax_tree.json.gz", json.dumps(ax))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"accessibility tree: {exc!r}")

    verdict = None
    try:
        from auto_apply.adapters.secondary.browser.selenium_adapter import (
            SeleniumAdapter,
        )
        from auto_apply.adapters.secondary.perception.math_dom_adapter import (
            MathDOMAdapter,
        )

        adapter = MathDOMAdapter(SeleniumAdapter(driver))
        raw = driver.execute_script(
            adapter._script
        )  # AA's own extraction script, unchanged
        sizes["aa_extraction.json"] = _gz_write(
            folder / "aa_extraction.json.gz", json.dumps(raw)
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"AA extraction: {exc!r}")
    try:
        from auto_apply.domain.services.page_assessment import assess_page

        a = assess_page(url=url, title=title, html=html)
        verdict = {
            "kind": getattr(a.kind, "name", str(a.kind)),
            "confidence": a.confidence,
            "signals": list(a.signals),
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"AA page verdict: {exc!r}")

    meta = {
        "tool": "aa_capture",
        "tool_version": TOOL_VERSION,
        "captured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": "owner",
        "url": url,
        "title": title,
        "items": [{"id": it["id"], "description": it["description"]} for it in items],
        "windows_open": len(handles),
        "browser_version": driver.capabilities.get("browserVersion"),
        "viewport": driver.execute_script(
            "return [window.innerWidth, window.innerHeight, devicePixelRatio]"
        ),
        "frames": frames,
        "sizes_uncompressed": sizes,
        "aa_page_verdict": verdict,
        "errors": errors,
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    _ensure_venv()
    import tkinter as tk

    import yaml

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checklist", type=Path, default=CAPTURES / "checklist.yaml")
    args = parser.parse_args()
    if not args.checklist.is_file():
        sys.exit(f"Checklist not found: {args.checklist}")
    items = yaml.safe_load(args.checklist.read_text(encoding="utf-8"))["items"]
    ids = [it["id"] for it in items]
    if len(set(ids)) != len(ids) or any(
        not re.fullmatch(r"[a-z0-9-]+", i) for i in ids
    ):
        sys.exit("Checklist ids must be unique, lowercase letters, digits and dashes.")

    browser = Browser()
    root = tk.Tk()
    root.title("AA capture")
    root.attributes("-topmost", True)

    def count(item_id: str) -> int:
        d = CAPTURES / item_id
        return sum(1 for p in d.iterdir() if p.is_dir()) if d.is_dir() else 0

    vars_: list[tk.IntVar] = []
    checks: list[tk.Checkbutton] = []
    box = tk.Frame(root, padx=8, pady=6)
    box.pack(fill="both")

    def label(it: dict) -> str:
        n, need = count(it["id"]), it.get("need", 3)
        return f"{'[done] ' if n >= need else ''}{it['description']}   ({n}/{need})"

    for it in items:
        v = tk.IntVar()
        cb = tk.Checkbutton(
            box,
            text=label(it),
            variable=v,
            anchor="w",
            justify="left",
            wraplength=520,
            command=lambda: extract_btn.config(
                state="normal" if any(x.get() for x in vars_) else "disabled"
            ),
        )
        cb.pack(fill="x", anchor="w")
        vars_.append(v)
        checks.append(cb)

    row = tk.Frame(root, padx=8, pady=6)
    row.pack(fill="x")
    status = tk.Label(
        root,
        text="Browse in the new Chrome window, tick what the page matches, press Extract.",
        anchor="w",
        justify="left",
        wraplength=540,
        padx=8,
        pady=6,
    )

    def do_extract() -> None:
        chosen = [it for it, v in zip(items, vars_) if v.get()]
        if not chosen:
            return
        status.config(text="Saving...")
        root.update_idletasks()
        try:
            tab = browser.active_tab()
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            host = _slug(urlparse(tab.get("url", "")).hostname or "")
            folders = [CAPTURES / it["id"] / f"{stamp}_{host}" for it in chosen]
            meta = capture(browser.driver, folders[0], chosen, tab["id"])
            for extra in folders[1:]:
                shutil.copytree(folders[0], extra)
            last.clear()
            last.extend(folders)
            undo_btn.config(state="normal")
            with (CAPTURES / "index.tsv").open("a", encoding="utf-8") as log:
                log.write(
                    "\t".join(
                        [
                            stamp,
                            ",".join(it["id"] for it in chosen),
                            meta["title"].replace("\t", " "),
                            meta["url"],
                            str(len(meta["errors"])),
                        ]
                    )
                    + "\n"
                )
            note = (
                f"\n{len(meta['errors'])} part(s) not saved: see meta.json"
                if meta["errors"]
                else ""
            )
            saved = (meta["title"] or meta["url"])[:80]
            status.config(
                text=f"Saved: {saved}\n{host}  ->  {', '.join(it['id'] for it in chosen)}{note}"
            )
        except Exception as exc:  # noqa: BLE001 - show, never crash the window
            status.config(text=f"Not saved: {exc!r}")
        for it, v, cb in zip(items, vars_, checks):
            v.set(0)
            cb.config(text=label(it))
        extract_btn.config(state="disabled")

    last: list[Path] = []

    def do_undo() -> None:
        for folder in last:
            shutil.rmtree(folder, ignore_errors=True)
        stamp = last[0].name.split("_", 1)[0] if last else ""
        index = CAPTURES / "index.tsv"
        if stamp and index.is_file():
            lines = index.read_text(encoding="utf-8").splitlines(keepends=True)
            index.write_text(
                "".join(ln for ln in lines if not ln.startswith(stamp + "\t")),
                encoding="utf-8",
            )
        status.config(text=f"Removed the last capture ({len(last)} folder(s)).")
        last.clear()
        undo_btn.config(state="disabled")
        for it, cb in zip(items, checks):
            cb.config(text=label(it))

    extract_btn = tk.Button(
        row, text="Extract", width=16, state="disabled", command=do_extract
    )
    extract_btn.grid(row=0, column=0, padx=4)
    undo_btn = tk.Button(
        row, text="Undo last", width=16, state="disabled", command=do_undo
    )
    undo_btn.grid(row=0, column=1, padx=4)
    tk.Button(row, text="(reserved)", width=16, state="disabled").grid(
        row=0, column=2, padx=4
    )
    status.pack(fill="x")

    def on_close() -> None:
        browser.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    try:
        root.mainloop()
    finally:
        browser.close()


if __name__ == "__main__":
    main()
