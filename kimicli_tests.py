"""kimicli.py v3 - the proof. Parser, edit engine, applier, rollback, undo,
session flow, property/fuzz tests, and end-to-end runs through main() with a
fake streaming API.

Run from the folder holding kimicli.py:
    python -m pytest kimicli_tests.py -q

Every test works in a throwaway folder; nothing touches your repo. One test
re-checks undo of manifests written by the OLD kimicli: it runs only when
KIMICLI_V2 points at a copy of the old script."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
KIMI_DIR = Path(os.environ.get("KIMICLI_DIR", HERE))
sys.path.insert(0, str(KIMI_DIR))
import kimicli as K  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    root = tmp_path / "AA"
    root.mkdir()
    monkeypatch.setattr(K, "PROJECT_ROOT", root.resolve())
    monkeypatch.setattr(K, "OUT_DIR", root / ".kimi_out")
    monkeypatch.setattr(K, "BACKUP_DIR", root / ".kimi_backups")
    monkeypatch.setattr(K, "LEDGER", root / ".kimi_out" / "ledger.jsonl")
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    (root / ".kimi_out").mkdir()
    return root


def w(root: Path, rel: str, data) -> Path:
    p = root.joinpath(*rel.split("/"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def edit(path: str, search: str, replace: str) -> str:
    return f"### EDIT: {path}\n<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n"


def props(root: Path, reply: str):
    pr = K.parse_changes(reply)
    groups, gp = K.group_blocks(pr, root)
    return [K._proposal_from_group(g, "t", root) for g in groups], pr, gp


def applier(root: Path, **kw) -> "K.Applier":
    return K.Applier(root, root / ".kimi_backups", K.ApplyOptions(**kw))


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and not ({".kimi_backups", ".kimi_out", ".git"} & set(p.parts))}


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


# =========================================================================
# PARSER
# =========================================================================

class TestParser:
    def test_basic_edit_file_end(self):
        r = ("Files:\n- a.py - EDIT - x\n- b.md - FILE - y\n\n" + edit("a.py", "x = 1\n", "x = 2\n")
             + "### FILE: b.md\n```markdown\n# B\n```\n### END CHANGES\n")
        pr = K.parse_changes(r)
        assert [b.kind for b in pr.blocks] == ["edit", "file"]
        assert pr.blocks[0].edit.search == "x = 1\n" and pr.blocks[0].edit.replace == "x = 2\n"
        assert pr.blocks[1].content == "# B\n"
        assert pr.end_marker and not pr.problems
        assert [(p, k) for _, p, k in pr.announced] == [("a.py", "edit"), ("b.md", "file")]

    def test_blocks_after_end_are_not_staged(self):
        r = edit("a.py", "x\n", "y\n") + "### END CHANGES\n\nBETTER IDEA\n" + edit("a.py", "y\n", "z\n")
        pr = K.parse_changes(r)
        assert len(pr.blocks) == 1 and pr.blocks_after_end == 1
        assert not pr.errors and pr.warnings

    def test_fenced_edit_and_code_fence_inside_replace(self):
        r = ("### EDIT: docs/x.md\n```\n<<<<<<< SEARCH\nold\n=======\nnew\n```python\nprint(1)\n```\n"
             ">>>>>>> REPLACE\n```\n### END CHANGES\n")
        pr = K.parse_changes(r)
        assert not pr.problems
        assert pr.blocks[0].edit.replace == "new\n```python\nprint(1)\n```\n"

    def test_aider_style_path_line(self):
        r = "pkg/a.py\n```python\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n```\n"
        pr = K.parse_changes(r)
        assert pr.blocks[0].path == "pkg/a.py" and pr.blocks[0].style == "aider" and not pr.errors

    def test_diff_fenced_style(self):
        r = "```\npkg/a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n```\n"
        pr = K.parse_changes(r)
        assert pr.blocks[0].path == "pkg/a.py" and not pr.errors

    def test_orphan_block_without_path_is_error(self):
        pr = K.parse_changes("Here:\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n")
        assert not pr.blocks and len(pr.errors) == 1

    def test_legacy_patch_four_char_markers(self):
        pr = K.parse_changes("### PATCH: a.py\n```python\n<<<<\nx = 1\n====\nx = 2\n>>>>\n```\n")
        assert len(pr.blocks) == 1 and pr.blocks[0].edit.search == "x = 1\n"

    @pytest.mark.parametrize("cut", [
        "### EDIT: a.py\n<<<<<<< SEARCH\nx = 1\n",
        "### EDIT: a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n",
        "### FILE: a.py\n```python\nx = 1\n",
        "### EDIT: a.py\n",
        "### EDIT: a.py\n<<<<<<< SEA",
    ])
    def test_truncations_are_errors_never_partial_blocks(self, cut):
        pr = K.parse_changes(cut)
        assert not pr.blocks and pr.errors

    def test_second_divider_is_ambiguous(self):
        pr = K.parse_changes("### EDIT: a.md\n<<<<<<< SEARCH\nTitle\n=======\n=======\nx\n>>>>>>> REPLACE\n")
        assert not pr.blocks and "second" in pr.errors[0].message

    def test_header_cleanup_backticks_and_description(self):
        pr = K.parse_changes("### EDIT: `pkg/a.py` (adds retry)\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n")
        assert pr.blocks[0].path == "pkg/a.py"

    def test_loose_header_is_reported(self):
        pr = K.parse_changes("**FILE:** pkg/a.py\n```python\nx = 1\n```\n")
        assert not pr.blocks and pr.errors

    def test_delete_block_refused_and_prose_heading_ignored(self):
        pr = K.parse_changes("### Ruling: keep it\nprose here\n\n### DELETE: pkg/a.py\n```\nx\n```\n")
        assert len(pr.errors) == 1 and "delete" in pr.errors[0].message.lower()

    def test_markdown_file_cut_at_inner_fence_is_error(self):
        pr = K.parse_changes("### FILE: docs/a.md\n```markdown\n# A\n```python\nx\n```\nmore\n```\n")
        assert pr.errors and "LONGER" in pr.errors[0].message

    def test_longer_fence_keeps_markdown_whole(self):
        pr = K.parse_changes("### FILE: docs/a.md\n````markdown\n# A\n```python\nx\n```\nmore\n````\n")
        assert not pr.problems and pr.blocks[0].content.endswith("more\n")

    def test_crlf_reply(self):
        pr = K.parse_changes(edit("a.py", "x\n", "y\n").replace("\n", "\r\n"))
        assert pr.blocks[0].edit.search == "x\n"

    def test_indented_marker_reported(self):
        pr = K.parse_changes("### EDIT: a.py\n    <<<<<<< SEARCH\n    x\n    =======\n    y\n    >>>>>>> REPLACE\n")
        assert pr.errors and not pr.blocks

    def test_header_with_no_block(self):
        pr = K.parse_changes("### EDIT: a.py\nI decided not to change it.\n")
        assert pr.errors

    def test_edit_text_inside_file_body_is_content(self):
        body = "# doc\n### EDIT: x.py\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
        pr = K.parse_changes("### FILE: docs/k.md\n````\n" + body + "````\n")
        assert len(pr.blocks) == 1 and pr.blocks[0].kind == "file" and pr.blocks[0].content == body

    def test_udiff_is_warning(self):
        pr = K.parse_changes("```diff\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n```\n")
        assert not pr.errors and pr.warnings

    def test_doctest_prompt_not_mistaken(self):
        pr = K.parse_changes("Example:\n>>> print(1)\n1\n")
        assert not pr.problems

    def test_sept3_incident_shape_all_seven_blocks_seen(self):
        reply = ""
        for n in range(2):
            reply += f"### PATCH: packages/auto_apply/src/auto_apply/application/workflows/applications_workflow.py\n```python\n<<<<\nold{n}\n====\nnew{n}\n>>>>\n```\n"
        for n in range(3):
            reply += f"### PATCH: packages/auto_apply/src/auto_apply/domain/models/profile.py\n```python\n<<<<\np{n}\n====\nq{n}\n>>>>\n```\n"
        reply += "### FILE: packages/auto_apply/src/auto_apply/adapters/primary/gui/settings_editor.py\n```python\nx = 1\n```\n"
        reply += "### FILE: packages/auto_apply/tests/workflows/test_document_upload_resolution.py\n```python\ny = 1\n```\n"
        pr = K.parse_changes(reply)
        groups, _ = K.group_blocks(pr, Path("/tmp/AA"))
        assert len(pr.blocks) == 7 and len(groups) == 4
        assert len([g for g in groups if g.kind == "edit"][1].edits) == 3


# =========================================================================
# EDIT ENGINE
# =========================================================================

class TestEngine:
    def run(self, text, *pairs):
        eds = [K.EditBlock(s, r, 0) for s, r in pairs]
        return K.apply_edits(text, eds)

    def test_exact(self):
        out, oc = self.run("a\nb\nc\n", ("b\n", "B\n"))
        assert out == "a\nB\nc\n" and oc[0].status == "applied"

    def test_not_found_has_diag(self):
        out, oc = self.run("def f():\n    return 1\n", ("def f():\n    return 2\n", "x\n"))
        assert oc[0].status == "failed" and oc[0].diag and oc[0].diag["line"] == 1

    def test_ambiguous(self):
        _, oc = self.run("x = 1\ny\nx = 1\n", ("x = 1\n", "x = 2\n"))
        assert oc[0].status == "failed" and "2 places" in oc[0].problem

    def test_never_matches_mid_line(self):
        # 'x = 1' must not hit the tail of 'max = 1'
        _, oc = self.run("max = 1\n", ("x = 1\n", "x = 2\n"))
        assert oc[0].status == "failed"

    def test_prefix_trap_from_real_incident(self):
        text = ('            tag = element.get_attribute("tagName").lower()\n'
                '            tag = element.get_attribute("tagName").lower() if element else "?"\n')
        out, oc = self.run(text, ('            tag = element.get_attribute("tagName").lower()\n',
                                  '            tag = (element.get_attribute("tagName") or "").lower()\n'))
        assert oc[0].status == "applied"
        assert out.splitlines()[1].endswith('if element else "?"')

    def test_sequential(self):
        out, _ = self.run("a\nb\n", ("a\n", "a1\n"), ("a1\nb\n", "a1\nb1\n"))
        assert out == "a1\nb1\n"

    def test_deletion(self):
        out, _ = self.run("a\nb\nc\n", ("b\n", ""))
        assert out == "a\nc\n"

    def test_crlf_preserved_and_replacement_converted(self):
        out, _ = self.run("a\r\nb\r\nc\r\n", ("b\n", "B\nB2\n"))
        assert out == "a\r\nB\r\nB2\r\nc\r\n"

    def test_no_trailing_newline(self):
        out, oc = self.run("a\nlast", ("last\n", "LAST\n"))
        assert out == "a\nLAST" and oc[0].status == "applied"

    def test_trailing_whitespace_tolerated_whole_lines_only(self):
        out, oc = self.run("def f():  \n    pass\n", ("def f():\n    pass\n", "def g():\n    pass\n"))
        assert out == "def g():\n    pass\n" and "trailing" in oc[0].how

    def test_indentation_difference_is_not_tolerated(self):
        _, oc = self.run("        return x\n", ("    return x\n", "    return y\n"))
        assert oc[0].status == "failed"

    def test_additive_already_present_is_have(self):
        text = "import a\nimport b\n\ndef f():\n    pass\n"
        out, oc = self.run(text, ("import a\n", "import a\nimport b\n"))
        assert out == text and oc[0].status == "have"

    def test_additive_not_present_applies_once(self):
        out, oc = self.run("import a\n", ("import a\n", "import a\nimport b\n"))
        assert out == "import a\nimport b\n"

    def test_replace_mode_have_needs_distinctive_text(self):
        # SEARCH absent + a short common REPLACE present elsewhere -> NOT 'have' (fail closed)
        _, oc = self.run("x = 0\npass\n", ("raise ValueError()\n", "pass\n"))
        assert oc[0].status == "failed"

    def test_empty_search_rejected(self):
        _, oc = self.run("a\n", ("", "b\n"))
        assert oc[0].status == "failed"

    def test_elision_in_search_explained(self):
        _, oc = self.run("def f():\n    return 1\n", ("def f():\n    # ... existing code\n", "x\n"))
        assert "placeholder" in oc[0].problem

    def test_blank_first_line_search(self):
        out, _ = self.run("a\n\nb\n", ("\nb\n", "\nB\n"))
        assert out == "a\n\nB\n"

    def test_mixed_endings_untouched_lines_byte_identical(self):
        out, _ = self.run("a\r\nb\nc\r\n", ("b\n", "B\n"))
        assert out.startswith("a\r\n") and out.endswith("c\r\n")


# =========================================================================
# APPLIER / TRANSACTION / UNDO
# =========================================================================

class TestApplier:
    def test_clean_apply_then_undo_bytes_exact(self, repo):
        w(repo, "pkg/a.py", b"\xef\xbb\xbfx = 1\r\ny = 2\r\n")
        before = tree(repo)
        pp, _, _ = props(repo, edit("pkg/a.py", "y = 2\n", "y = 3\n"))
        man = quiet(applier(repo).apply, applier(repo).validate(pp), {})
        assert (repo / "pkg/a.py").read_bytes() == b"\xef\xbb\xbfx = 1\r\ny = 3\r\n"
        assert man["status"] == "complete"
        assert quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True) == 0
        assert tree(repo) == before

    def test_problem_anywhere_blocks_everything(self, repo):
        w(repo, "a.py", "x = 1\n")
        w(repo, "b.py", "y = 1\n")
        before = tree(repo)
        pp, _, _ = props(repo, edit("a.py", "x = 1\n", "x = 2\n") + edit("b.py", "nope\n", "z\n"))
        plans = applier(repo).validate(pp)
        assert plans[1].problems
        with pytest.raises(K.ApplyAborted):
            applier(repo).apply(plans, {})
        assert tree(repo) == before and not list((repo / ".kimi_backups").glob("manifest_*")) if (repo / ".kimi_backups").exists() else True

    @pytest.mark.parametrize("fail_at", [1, 2, 3])
    def test_rollback_on_any_write(self, repo, fail_at):
        for n in "abc":
            w(repo, f"{n}.py", f"{n} = 1\r\n")
        before = tree(repo)
        pp, _, _ = props(repo, "".join(edit(f"{n}.py", f"{n} = 1\n", f"{n} = 2\n") for n in "abc"))
        calls = {"n": 0}

        def flaky(path, data, keep=None):
            calls["n"] += 1
            if calls["n"] == fail_at:
                raise PermissionError("locked")
            K.write_bytes_atomic(path, data, keep)

        ap = applier(repo)
        with pytest.raises(K.ApplyAborted, match="restored"):
            ap.apply(ap.validate(pp), {}, _write=flaky)
        assert tree(repo) == before
        assert K.list_manifests(repo / ".kimi_backups")[-1]["status"] == "rolled_back"

    def test_keyboard_interrupt_mid_apply_rolls_back(self, repo):
        w(repo, "a.py", "a = 1\n")
        w(repo, "b.py", "b = 1\n")
        before = tree(repo)
        pp, _, _ = props(repo, edit("a.py", "a = 1\n", "a = 2\n") + edit("b.py", "b = 1\n", "b = 2\n"))
        calls = {"n": 0}

        def interrupt(path, data, keep=None):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt
            K.write_bytes_atomic(path, data, keep)

        ap = applier(repo)
        with pytest.raises(K.ApplyAborted):
            ap.apply(ap.validate(pp), {}, _write=interrupt)
        assert tree(repo) == before

    def test_toctou_file_changed_between_passes(self, repo):
        w(repo, "a.py", "a = 1\n")
        pp, _, _ = props(repo, edit("a.py", "a = 1\n", "a = 2\n"))
        ap = applier(repo)
        plans = ap.validate(pp)
        w(repo, "a.py", "a = 1\n# my edit\n")
        with pytest.raises(K.ApplyAborted, match="changed while"):
            ap.apply(plans, {})
        assert (repo / "a.py").read_text() == "a = 1\n# my edit\n"

    def test_hard_crash_leaves_undoable_manifest(self, repo, tmp_path):
        """Simulated power cut: the process dies between writes, so no rollback
        runs. The manifest was written first, so --undo repairs it."""
        for n in "ab":
            w(repo, f"{n}.py", f"{n} = 1\r\n")
        before = tree(repo)
        script = tmp_path / "crash.py"
        script.write_text(f"""
import sys, os
sys.path.insert(0, {str(KIMI_DIR)!r})
import kimicli as K
from pathlib import Path
root = Path({str(repo)!r})
pr = K.parse_changes(open({str(tmp_path / 'r.md')!r}).read())
g, _ = K.group_blocks(pr, root)
pp = [K._proposal_from_group(x, 't', root) for x in g]
ap = K.Applier(root, root / '.kimi_backups', K.ApplyOptions())
n = {{'c': 0}}
def w(p, d, k=None):
    n['c'] += 1
    K.write_bytes_atomic(p, d, k)
    if n['c'] == 1:
        os._exit(9)
ap.apply(ap.validate(pp), {{}}, _write=w)
""")
        (tmp_path / "r.md").write_text(edit("a.py", "a = 1\n", "a = 2\n") + edit("b.py", "b = 1\n", "b = 2\n"))
        rc = subprocess.run([sys.executable, str(script)]).returncode
        assert rc == 9
        assert (repo / "a.py").read_bytes() == b"a = 2\r\n"          # half-applied on disk
        m = K.list_manifests(repo / ".kimi_backups")[-1]
        assert m["status"] == "writing"
        assert quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True) == 0
        assert tree(repo) == before

    def test_undo_idempotent_and_skips_undone(self, repo):
        w(repo, "a.py", "a = 1\n")
        pp, _, _ = props(repo, edit("a.py", "a = 1\n", "a = 2\n"))
        quiet(applier(repo).apply, applier(repo).validate(pp), {})
        assert quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True) == 0
        assert quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True) == 1
        assert (repo / "a.py").read_text() == "a = 1\n"

    def test_undo_last_picks_newest_even_same_second(self, repo):
        w(repo, "a.py", "a = 1\n")
        w(repo, "b.py", "b = 1\n")
        for f, s, r in (("a.py", "a = 1\n", "a = 2\n"), ("b.py", "b = 1\n", "b = 2\n")):
            pp, _, _ = props(repo, edit(f, s, r))
            quiet(applier(repo).apply, applier(repo).validate(pp), {})
        quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True)
        assert (repo / "b.py").read_text() == "b = 1\n" and (repo / "a.py").read_text() == "a = 2\n"

    def test_undo_refuses_conflict_all_or_nothing(self, repo):
        w(repo, "a.py", "a = 1\n")
        w(repo, "b.py", "b = 1\n")
        pp, _, _ = props(repo, edit("a.py", "a = 1\n", "a = 2\n") + edit("b.py", "b = 1\n", "b = 2\n"))
        quiet(applier(repo).apply, applier(repo).validate(pp), {})
        w(repo, "b.py", "b = 2\n# mine\n")
        assert quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True) == 1
        assert (repo / "a.py").read_text() == "a = 2\n"             # untouched: all-or-nothing

    def test_undo_refuses_damaged_backup_even_with_force(self, repo):
        w(repo, "a.py", "a = 1\n")
        pp, _, _ = props(repo, edit("a.py", "a = 1\n", "a = 2\n"))
        man = quiet(applier(repo).apply, applier(repo).validate(pp), {})
        bk = repo / ".kimi_backups" / man["entries"][0]["backup"]
        bk.write_bytes(b"corrupt")
        assert quiet(K.undo, repo, repo / ".kimi_backups", "last", force=True, assume_yes=True) == 1
        assert (repo / "a.py").read_text() == "a = 2\n"

    def test_undo_other_root_refused(self, repo, tmp_path):
        w(repo, "a.py", "a = 1\n")
        pp, _, _ = props(repo, edit("a.py", "a = 1\n", "a = 2\n"))
        quiet(applier(repo).apply, applier(repo).validate(pp), {})
        other = tmp_path / "other"
        other.mkdir()
        assert quiet(K.undo, other, repo / ".kimi_backups", "last", assume_yes=True) == 1

    def test_create_and_undo_removes_file_and_dirs(self, repo):
        w(repo, "pkg/x.py", "x = 1\n")
        before = tree(repo)
        pp, _, _ = props(repo, "### FILE: pkg/new/deep/m.py\n```python\nm = 1\n```\n")
        plans = applier(repo, allow_new_files=True).validate(pp)
        assert "--allow-new-dirs" in plans[0].problems[0]
        plans = applier(repo, allow_new_files=True, allow_new_dirs=True).validate(pp)
        quiet(applier(repo).apply, plans, {})
        assert (repo / "pkg/new/deep/m.py").exists()
        quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True)
        assert tree(repo) == before and not (repo / "pkg/new").exists()

    def test_new_file_needs_flag(self, repo):
        w(repo, "pkg/x.py", "x\n")
        pp, _, _ = props(repo, "### FILE: pkg/y.py\n```python\ny = 1\n```\n")
        assert "--allow-new-files" in applier(repo).validate(pp)[0].problems[0]

    def test_old_bug5_new_file_never_overwrites_same_basename(self, repo):
        victim = w(repo, "pkg/other/utils.py", "# unrelated\n" * 50)
        pp, _, _ = props(repo, "### FILE: pkg/newmod/utils.py\n```python\n" + "# new\n" * 50 + "```\n")
        pl = applier(repo, allow_new_files=True, allow_new_dirs=True).validate(pp)
        assert pl[0].action == "create" and pl[0].rel == "pkg/newmod/utils.py"
        quiet(applier(repo).apply, pl, {})
        assert victim.read_text() == "# unrelated\n" * 50

    def test_mispathed_create_refused(self, repo):
        w(repo, "packages/auto_apply/tests/test_x.py", "x\n")
        pp, _, _ = props(repo, "### FILE: tests/test_x.py\n```python\nx = 1\n```\n")
        pl = applier(repo, allow_new_files=True, allow_new_dirs=True).validate(pp)
        assert any("mis-pathed" in p for p in pl[0].problems)

    def test_edit_path_prefix_corrected_only_when_unique(self, repo):
        w(repo, "packages/auto_apply/src/auto_apply/m.py", "a = 1\n")
        pp, _, _ = props(repo, edit("src/auto_apply/m.py", "a = 1\n", "a = 2\n"))
        pl = applier(repo).validate(pp)
        assert not pl[0].problems and pl[0].rel == "packages/auto_apply/src/auto_apply/m.py"
        w(repo, "packages/other/src/auto_apply/m.py", "a = 1\n")
        pl = applier(repo).validate(pp)
        assert pl[0].problems

    def test_basename_only_edit_never_rerouted(self, repo):
        w(repo, "pkg/deep/m.py", "a = 1\n")
        pp, _, _ = props(repo, edit("m.py", "a = 1\n", "a = 2\n"))
        assert applier(repo).validate(pp)[0].problems

    def test_repo_name_prefix_stripped_unless_real_dir(self, repo):
        w(repo, "pkg/m.py", "a = 1\n")
        pp, _, _ = props(repo, edit("AA/pkg/m.py", "a = 1\n", "a = 2\n"))
        assert applier(repo).validate(pp)[0].rel == "pkg/m.py"

    @pytest.mark.parametrize("bad", ["../x.py", "/etc/passwd/../../x", "C:\\x.py", "c:x.py",
                                     "\\\\srv\\s\\x.py", "a.py:ads", "pkg/NUL.txt", "pkg/com1.py",
                                     "pkg/x.py.", "pkg /x.py", "pkg/KIMICL~1.PY", "pkg/a<b.py",
                                     "Kimicli.py", "sub/.GIT/config", ".env", "pkg/.venv/x.py",
                                     "packages/auto_apply/docs/old_retired_files/x.py", "dev_data/p.db",
                                     "retire.py", "callapi.py"])
    def test_path_refusals(self, repo, bad):
        pl = applier(repo, allow_new_files=True, allow_new_dirs=True).validate(
            [K.Proposal(raw_path=bad, kind="file", content="x = 1\n")])
        assert pl[0].problems, bad

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
    def test_symlink_refused(self, repo, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "t.py").write_text("x = 1\n")
        os.symlink(outside, repo / "link")
        pl = applier(repo).validate([K.Proposal(raw_path="link/t.py", kind="edit",
                                                edits=[K.EditBlock("x = 1\n", "x = 2\n", 1)])])
        assert pl[0].problems and (outside / "t.py").read_text() == "x = 1\n"
        w(repo, "real.py", "x = 1\n")
        os.symlink(repo / "real.py", repo / "alias.py")
        pl = applier(repo).validate([K.Proposal(raw_path="alias.py", kind="file", content="y\n")])
        assert pl[0].problems

    def test_case_variant_duplicates(self, repo):
        w(repo, "pkg/a.py", "a = 1\nb = 1\n")
        pp, _, _ = props(repo, edit("pkg/a.py", "a = 1\n", "a = 2\n"))
        pp2, _, _ = props(repo, "### FILE: PKG/A.py\n```python\nz = 1\n```\n")
        pl = applier(repo, allow_new_files=True, allow_new_dirs=True).validate(pp + pp2)
        if (repo / "PKG").exists():          # case-insensitive filesystem
            assert all(p.problems for p in pl)
        else:
            assert any("twice" in x for p in pl for x in p.problems)

    def test_non_utf8_refused(self, repo):
        w(repo, "c.txt", b"caf\xe9\nline2\n")
        pl = applier(repo).validate([K.Proposal(raw_path="c.txt", kind="edit",
                                                edits=[K.EditBlock("line2\n", "x\n", 1)])])
        assert "UTF-8" in pl[0].problems[0]
        pl = applier(repo).validate([K.Proposal(raw_path="c.txt", kind="file", content="x\n")])
        assert pl[0].problems

    def test_file_shrink_guard_and_identical(self, repo):
        w(repo, "big.py", "".join(f"x{i} = {i}\n" for i in range(100)))
        pl = applier(repo).validate([K.Proposal(raw_path="big.py", kind="file", content="x = 1\n")])
        assert any("shrank" in p for p in pl[0].problems)
        same = (repo / "big.py").read_text().replace("\n", "\n")
        pl = applier(repo).validate([K.Proposal(raw_path="big.py", kind="file", content=same)])
        assert pl[0].action == "identical"

    def test_file_crlf_kept_on_overwrite(self, repo):
        w(repo, "w.py", b"a = 1\r\n")
        pl = applier(repo).validate([K.Proposal(raw_path="w.py", kind="file", content="a = 2\n")])
        assert pl[0].new_bytes == b"a = 2\r\n"

    def test_gitattributes_eol_for_new_files(self, repo):
        w(repo, ".gitattributes", "* text=auto eol=lf\n*.bat text eol=crlf\n")
        pl = applier(repo, allow_new_files=True).validate([
            K.Proposal(raw_path="run.bat", kind="file", content="echo 1\necho 2\n"),
            K.Proposal(raw_path="x.py", kind="file", content="a = 1\n")])
        assert pl[0].new_bytes == b"echo 1\r\necho 2\r\n" and pl[1].new_bytes == b"a = 1\n"

    def test_stale_whole_file_refused(self, repo):
        w(repo, "s.py", "a = 1\n")
        prop = K.Proposal(raw_path="s.py", kind="file", content="a = 9\n",
                          base_sha=sha(b"a = 0\n"))
        assert any("AFTER this reply" in p for p in applier(repo).validate([prop])[0].problems)
        prop2 = K.Proposal(raw_path="s.py", kind="file", content="a = 9\n", known_bases=["a = 0\n"])
        assert any("STALE BASE" in p for p in applier(repo).validate([prop2])[0].problems)
        assert not applier(repo, allow_stale=True).validate([prop2])[0].problems
        prop3 = K.Proposal(raw_path="s.py", kind="file", content="a = 9\n", known_bases=["a = 1  \n"])
        assert not applier(repo).validate([prop3])[0].problems

    def test_edits_rebase_onto_drifted_file(self, repo):
        w(repo, "d.py", "top = 1\n\ndef f():\n    return 1\n")
        prop = K.Proposal(raw_path="d.py", kind="edit", base_sha=sha(b"old"),
                          edits=[K.EditBlock("def f():\n    return 1\n", "def f():\n    return 2\n", 1)])
        pl = applier(repo).validate([prop])
        assert not pl[0].problems and any("re-anchored" in n for n in pl[0].notes)

    def test_placeholder_in_replace_refused(self, repo):
        w(repo, "p.py", "def f():\n    a = 1\n    return a\n")
        pp, _, _ = props(repo, edit("p.py", "def f():\n    a = 1\n    return a\n",
                                    "def f():\n    # ... rest unchanged\n"))
        assert any("placeholder" in p for p in applier(repo).validate(pp)[0].problems)

    def test_syntax_json_toml_checks(self, repo):
        w(repo, "a.py", "x = 1\n")
        w(repo, "c.json", '{"a": 1}\n')
        w(repo, "t.toml", 'a = 1\n')
        pp, _, _ = props(repo, edit("a.py", "x = 1\n", "x = (\n") + edit("c.json", '{"a": 1}\n', '{"a": }\n')
                         + edit("t.toml", "a = 1\n", "a = \n"))
        pl = applier(repo).validate(pp)
        assert pl[0].problems and pl[1].problems
        try:
            import tomllib  # noqa: F401  (3.11+; on 3.10 TOML is not validated)
            assert pl[2].problems
        except ImportError:
            assert not pl[2].problems


class TestCodeChecks:
    def test_new_undefined_name_only(self, repo):
        w(repo, "a.py", "import os\n\ndef f():\n    return old_missing\n")
        pp, _, _ = props(repo, edit("a.py", "import os\n", "import os\nx = os.sep\n"))
        assert not applier(repo).validate(pp)[0].problems          # pre-existing problem ignored
        pp, _, _ = props(repo, edit("a.py", "import os\n", "import os\nx = Path('.')\n"))
        assert "Path" in applier(repo).validate(pp)[0].problems[0]
        assert not applier(repo, skip_checks=True).validate(pp)[0].problems

    def test_type_checking_and_future_annotations_ok(self, repo):
        w(repo, "a.py", "from __future__ import annotations\nfrom typing import TYPE_CHECKING\n"
                        "if TYPE_CHECKING:\n    from b import B\n\ndef f(x: B) -> None:\n    pass\n")
        pp, _, _ = props(repo, edit("a.py", "def f(x: B) -> None:\n    pass\n",
                                    "def f(x: B, y: C) -> None:\n    pass\n"))
        assert not applier(repo).validate(pp)[0].problems

    def test_import_of_missing_name_across_files(self, repo):
        w(repo, "pkg/__init__.py", "")
        w(repo, "pkg/lib.py", "def helper():\n    return 1\n")
        w(repo, "pkg/use.py", "x = 1\n")
        pp, _, _ = props(repo, edit("pkg/use.py", "x = 1\n", "from pkg.lib import helper2\nx = helper2()\n"))
        assert any("helper2" in p for p in applier(repo).validate(pp)[0].problems)
        # ...but fine when the same batch adds helper2 to lib.py
        pp2, _, _ = props(repo, edit("pkg/use.py", "x = 1\n", "from pkg.lib import helper2\nx = helper2()\n")
                          + edit("pkg/lib.py", "def helper():\n", "def helper2():\n    return 2\n\n\ndef helper():\n"))
        assert not any(p.problems for p in applier(repo).validate(pp2))

    def test_relative_import_and_submodule(self, repo):
        w(repo, "pkg/__init__.py", "")
        w(repo, "pkg/sub/__init__.py", "")
        w(repo, "pkg/sub/mod.py", "V = 1\n")
        w(repo, "pkg/sub/use.py", "x = 1\n")
        pp, _, _ = props(repo, edit("pkg/sub/use.py", "x = 1\n", "from .mod import V\nfrom . import mod\nx = V\n"))
        assert not applier(repo).validate(pp)[0].problems
        pp, _, _ = props(repo, edit("pkg/sub/use.py", "x = 1\n", "from .mod import W\nx = W\n"))
        assert applier(repo).validate(pp)[0].problems

    def test_removed_name_still_imported_elsewhere(self, repo):
        w(repo, "pkg/__init__.py", "")
        w(repo, "pkg/lib.py", "def helper():\n    return 1\n")
        w(repo, "pkg/user.py", "from pkg.lib import helper\n")
        pp, _, _ = props(repo, edit("pkg/lib.py", "def helper():\n", "def renamed():\n"))
        assert any("pkg/user.py" in p for p in applier(repo).validate(pp)[0].problems)

    def test_dynamic_module_skipped(self, repo):
        w(repo, "pkg/__init__.py", "")
        w(repo, "pkg/dyn.py", "def __getattr__(n):\n    return n\n")
        w(repo, "pkg/u.py", "x = 1\n")
        pp, _, _ = props(repo, edit("pkg/u.py", "x = 1\n", "from pkg.dyn import anything\nx = anything\n"))
        assert not applier(repo).validate(pp)[0].problems

    def test_external_imports_ignored(self, repo):
        w(repo, "u.py", "x = 1\n")
        pp, _, _ = props(repo, edit("u.py", "x = 1\n", "from selenium.webdriver import Chrome\nx = Chrome\n"))
        assert not applier(repo).validate(pp)[0].problems


# =========================================================================
# LEGACY: manifests written by the OLD kimicli (v2) can still be undone
# =========================================================================

def test_undo_of_v2_manifest_including_crlf(repo, tmp_path, monkeypatch):
    old_src = os.environ.get("KIMICLI_V2")
    if not old_src or not Path(old_src).exists():
        pytest.skip("set KIMICLI_V2 to the old kimicli.py to run this")
    w(repo, "a.py", b"x = 1\r\ny = 2\r\n")
    w(repo, "b.py", b"z = 1\n")
    before = tree(repo)
    code = f"""
import os, sys, builtins
os.environ['KIMI_PROJECT_ROOT'] = {str(repo)!r}
sys.path.insert(0, {str(Path(old_src).parent)!r})
builtins.input = lambda *a, **k: 'y'
import importlib.util
spec = importlib.util.spec_from_file_location('v2', {old_src!r}); m = importlib.util.module_from_spec(spec); sys.modules['v2'] = m; spec.loader.exec_module(m)
ap = m.Applier(m.PROJECT_ROOT)
ap.apply(ap.validate([('a.py', 'x = 1\\ny = 3\\n'), ('b.py', 'z = 2\\n')]), dry_run=False)
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
    assert (repo / "a.py").read_bytes() == b"x = 1\r\ny = 3\r\n"
    assert quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True) == 0
    assert tree(repo) == before


# =========================================================================
# SESSION FLOW: stage -> repair -> resume -> apply -> undo
# =========================================================================

def ns(**kw):
    base = dict(dry_run=False, yes=True, allow_new_files=False, allow_new_dirs=False,
                allow_shrink=False, allow_stale=False, skip_checks=False, accept_parse_errors=False)
    base.update(kw)
    return argparse.Namespace(**base)


class TestSessionFlow:
    def new_session(self, repo, dump_files=None):
        s = K.Session()
        if dump_files:
            body = "".join(f"\n---\nFile: AA/{p}\n---\n{t}" for p, t in dump_files.items())
            s.messages = [{"role": "system", "content": f'<codebase name="AA-kimi.txt">\n{body}\n</codebase>'}]
        s.messages.append({"role": "user", "content": "task"})
        return s

    def test_good_turn_applies_and_undoes(self, repo):
        w(repo, "pkg/a.py", "a = 1\n")
        before = tree(repo)
        s = self.new_session(repo)
        reply = "Files:\n- pkg/a.py - EDIT - bump\n" + edit("pkg/a.py", "a = 1\n", "a = 2\n") + "### END CHANGES\n"
        summ = K.stage_turn(s, 1, reply, "stop")
        assert summ.repair_path is None and summ.preview_path.exists()
        pp, blocking, _ = K.load_session_proposals(s)
        assert not blocking
        assert quiet(K.run_apply, pp, ns(dry_run=True), blocking=blocking, session=s) == 0
        assert tree(repo) == before
        assert quiet(K.run_apply, pp, ns(), blocking=blocking, session=s) == 0
        assert (repo / "pkg/a.py").read_text() == "a = 2\n"
        assert quiet(K.undo, repo, repo / ".kimi_backups", "last", assume_yes=True) == 0
        assert tree(repo) == before

    def test_failed_turn_makes_repair_prompt_and_repair_supersedes(self, repo):
        w(repo, "pkg/a.py", "def f():\n    return 1\n")
        w(repo, "pkg/b.py", "b = 1\n")
        s = self.new_session(repo)
        r1 = (edit("pkg/a.py", "def f():\n    return 2\n", "def f():\n    return 3\n")
              + edit("pkg/b.py", "b = 1\n", "b = 2\n") + "### END CHANGES\n")
        summ = K.stage_turn(s, 1, r1, "stop")
        text = summ.repair_path.read_text()
        assert "pkg/a.py" in text and "return 1" in text and "[kimicli-repair-of-turn: 1]" in text
        assert "pkg/b.py" not in text.split("REPAIR REQUEST")[1].split("1.")[1] if "1." in text else True
        # apply now is refused
        pp, blocking, _ = K.load_session_proposals(s)
        assert quiet(K.run_apply, pp, ns(), blocking=blocking, session=s) == 1
        assert (repo / "pkg/b.py").read_text() == "b = 1\n"
        # the repair turn re-emits only a.py
        s.messages.append({"role": "user", "content": text})
        r2 = edit("pkg/a.py", "def f():\n    return 1\n", "def f():\n    return 3\n") + "### END CHANGES\n"
        assert K.stage_turn(s, 2, r2, "stop").repair_path is None
        pp, blocking, _ = K.load_session_proposals(s)
        assert not blocking and sorted(p.source for p in pp) == ["turn 1", "turn 2"]
        assert quiet(K.run_apply, pp, ns(), blocking=blocking, session=s) == 0
        assert (repo / "pkg/a.py").read_text().endswith("return 3\n") and (repo / "pkg/b.py").read_text() == "b = 2\n"

    def test_truncated_turn_blocks_until_repaired(self, repo):
        w(repo, "a.py", "a = 1\n")
        w(repo, "b.py", "b = 1\n")
        s = self.new_session(repo)
        r1 = edit("a.py", "a = 1\n", "a = 2\n") + "### EDIT: b.py\n<<<<<<< SEARCH\nb = 1\n=====\n"
        summ = K.stage_turn(s, 1, r1, "length")
        assert summ.repair_path is not None
        pp, blocking, _ = K.load_session_proposals(s)
        assert blocking and quiet(K.run_apply, pp, ns(), blocking=blocking, session=s) == 1
        assert (repo / "a.py").read_text() == "a = 1\n"            # the good half was NOT applied
        s.messages.append({"role": "user", "content": summ.repair_path.read_text()})
        K.stage_turn(s, 2, edit("b.py", "b = 1\n", "b = 2\n") + "### END CHANGES\n", "stop")
        pp, blocking, _ = K.load_session_proposals(s)
        assert not blocking
        assert quiet(K.run_apply, pp, ns(), blocking=blocking, session=s) == 0
        assert (repo / "a.py").read_text() == "a = 2\n" and (repo / "b.py").read_text() == "b = 2\n"

    def test_announced_but_missing_file_blocks(self, repo):
        w(repo, "a.py", "a = 1\n")
        w(repo, "b.py", "b = 1\n")
        s = self.new_session(repo)
        r = ("Files:\n1. a.py - EDIT - x\n2. b.py - EDIT - y\n\n" + edit("a.py", "a = 1\n", "a = 2\n")
             + "### END CHANGES\n")
        summ = K.stage_turn(s, 1, r, "stop")
        assert summ.repair_path and "b.py" in summ.repair_path.read_text()
        _, blocking, _ = K.load_session_proposals(s)
        assert blocking

    def test_stale_base_from_dump(self, repo):
        w(repo, "pkg/f.py", "a = 1\nb = 2  # added after the dump\n")
        s = self.new_session(repo, {"pkg/f.py": "a = 1\n"})
        summ = K.stage_turn(s, 1, "### FILE: pkg/f.py\n```python\na = 5\n```\n### END CHANGES\n", "stop")
        assert any("STALE BASE" in p for p in summ.plans[0].problems)
        s2 = self.new_session(repo, {"pkg/f.py": "a = 1\nb = 2  # added after the dump\n"})
        summ2 = K.stage_turn(s2, 1, "### FILE: pkg/f.py\n```python\na = 5\nb = 2\n```\n### END CHANGES\n", "stop")
        assert not summ2.plans[0].problems

    def test_turn_and_skip_selection(self, repo):
        w(repo, "a.py", "a = 1\n")
        w(repo, "b.py", "b = 1\n")
        s = self.new_session(repo)
        K.stage_turn(s, 1, edit("a.py", "a = 1\n", "a = 2\n") + "### END CHANGES\n", "stop")
        K.stage_turn(s, 2, edit("b.py", "b = 1\n", "b = 2\n") + "### END CHANGES\n", "stop")
        pp, _, _ = K.load_session_proposals(s, turns=[2])
        assert [p.raw_path for p in pp] == ["b.py"]
        pp, _, _ = K.load_session_proposals(s, skips=["a.py"])
        assert [p.raw_path for p in pp] == ["b.py"]

    def test_legacy_rows_still_apply(self, repo):
        w(repo, "pkg/old.py", "x = 1\n")
        s = self.new_session(repo)
        staged = s.dir / "proposed" / "pkg" / "old.py"
        staged.parent.mkdir(parents=True)
        staged.write_text("x = 2\n")
        (s.dir / "proposals.json").write_text(json.dumps([{
            "turn": 1, "path": "pkg/old.py", "sha256": "x", "lines": 2,
            "staged": "proposed/pkg/old.py"}]))
        pp, blocking, _ = K.load_session_proposals(s)
        assert pp[0].kind == "file" and not blocking
        assert quiet(K.run_apply, pp, ns(), blocking=blocking, session=s) == 0
        assert (repo / "pkg/old.py").read_text() == "x = 2\n"

    def test_reapply_of_applied_session_is_noop(self, repo):
        w(repo, "a.py", "import a\n")
        s = self.new_session(repo)
        K.stage_turn(s, 1, edit("a.py", "import a\n", "import a\nimport b\n") + "### END CHANGES\n", "stop")
        pp, bl, _ = K.load_session_proposals(s)
        quiet(K.run_apply, pp, ns(), blocking=bl, session=s)
        pp, bl, _ = K.load_session_proposals(s)
        quiet(K.run_apply, pp, ns(), blocking=bl, session=s)
        assert (repo / "a.py").read_text() == "import a\nimport b\n"


class TestImportResolutionRegressions:
    """Both found by auditing the checker against the real AA tree."""

    def test_stdlib_name_not_shadowed_by_nested_module(self, repo):
        w(repo, "src/auto_apply/__init__.py", "")
        w(repo, "src/auto_apply/domain/__init__.py", "")
        w(repo, "src/auto_apply/domain/types.py", "X = 1\n")
        w(repo, "src/auto_apply/u.py", "x = 1\n")
        pp, _, _ = props(repo, edit("src/auto_apply/u.py", "x = 1\n",
                                    "from types import SimpleNamespace\nx = SimpleNamespace()\n"))
        assert not applier(repo).validate(pp)[0].problems
        idx = K.FileIndex(repo)
        assert idx.module_file("types") is None
        assert idx.module_file("auto_apply.domain.types") == "src/auto_apply/domain/types.py"

    def test_import_guarded_by_try_except_importerror_not_judged(self, repo):
        w(repo, "pkg/__init__.py", "")
        w(repo, "pkg/lib.py", "A = 1\n")
        w(repo, "pkg/u.py", "x = 1\n")
        pp, _, _ = props(repo, edit("pkg/u.py", "x = 1\n",
                                    "try:\n    from pkg.lib import B\nexcept ImportError:\n    B = None\nx = B\n"))
        assert not applier(repo).validate(pp)[0].problems


def test_dump_repo_prefix_stripped_whatever_the_local_folder_is_called(tmp_path):
    root = tmp_path / "my-local-clone"
    (root / "packages" / "x").mkdir(parents=True)
    assert K.normalize_rel("AA/packages/x/m.py", root) == "packages/x/m.py"
    assert K.normalize_rel("my-local-clone/packages/x/m.py", root) == "packages/x/m.py"
    assert K.normalize_rel("tests/test_new.py", root) == "tests/test_new.py"      # never guessed away
    assert K.normalize_rel("src/auto_apply/m.py", root) == "src/auto_apply/m.py"
    (root / "AA").mkdir()
    assert K.normalize_rel("AA/packages/x/m.py", root) == "AA/packages/x/m.py"    # a real AA/ folder wins


def test_file_absent_at_staging_but_present_now_is_not_overwritten(repo):
    w(repo, "pkg/x.py", "x = 1\n")
    w(repo, "pkg/n.py", "someone else's new file\n")
    prop = K.Proposal(raw_path="pkg/n.py", kind="file", content="kimi's version\n", base_sha="")
    pl = applier(repo).validate([prop])
    assert any("did NOT exist" in p for p in pl[0].problems)


def test_wrong_case_path_keeps_on_disk_spelling(repo):
    w(repo, "pkg/Model.py", "a = 1\n")
    pl = applier(repo).validate([K.Proposal(raw_path="pkg/model.py", kind="edit",
                                            edits=[K.EditBlock("a = 1\n", "a = 2\n", 1)])])
    if (repo / "pkg" / "model.py").exists():          # case-insensitive filesystem
        assert pl[0].rel == "pkg/Model.py" and not pl[0].problems
    else:                                              # case-sensitive: never re-routed
        assert pl[0].problems


# =========================================================================
# PROPERTY / FUZZ TESTS
# =========================================================================

WORDS = ["x", "y = 1", "def f():", "    return x", "", "# note", "import os", "class A:",
         "    pass", "print('hi')", "=====", "value = compute(a, b)", "\tindent", "```", "  trailing  "]


def rand_lines(rng, n):
    return [rng.choice(WORDS) + (str(rng.randint(0, 3)) if rng.random() < 0.5 else "") for _ in range(n)]


def render(lines, eol_mode, rng, final_nl):
    out = []
    for i, ln in enumerate(lines):
        last = i == len(lines) - 1
        if last and not final_nl:
            out.append(ln)
            break
        eol = {"lf": "\n", "crlf": "\r\n"}.get(eol_mode) or rng.choice(["\n", "\r\n"])
        out.append(ln + eol)
    return "".join(out)


def test_engine_matches_reference_model():
    """For a random file and a random region that is unique as whole lines,
    apply_edits must equal the reference result: region replaced, every other
    byte identical, replacement using the file's dominant ending."""
    rng = random.Random(1234)
    checked = 0
    for _ in range(4000):
        n = rng.randint(1, 30)
        lines = rand_lines(rng, n)
        mode = rng.choice(["lf", "crlf", "mixed"])
        final_nl = rng.random() < 0.8
        text = render(lines, mode, rng, final_nl)
        # pick a region of whole lines
        a = rng.randint(0, n - 1)
        b = rng.randint(a + 1, min(n, a + 5))
        region_lines = lines[a:b]
        search = "".join(x + "\n" for x in region_lines)
        # uniqueness as whole-line runs in the LF-normalised text
        norm = text.replace("\r\n", "\n")
        hay = norm if norm.endswith("\n") else norm + "\n"
        occ = [p for p in range(len(hay)) if hay.startswith(search, p) and (p == 0 or hay[p - 1] == "\n")]
        repl_lines = rand_lines(rng, rng.randint(0, 4))
        replace = "".join(x + "\n" for x in repl_lines)
        if not search.strip():
            continue
        out, oc = K.apply_edits(text, [K.EditBlock(search, replace, 1)])
        additive = bool(replace) and search in replace
        if len(occ) != 1 or additive or search == replace:
            continue   # other outcomes are covered by targeted tests
        # reference: split original into lines WITH endings, splice
        with_ends = text.splitlines(keepends=True)
        eol = K.dominant_eol(text)
        new_mid = replace.replace("\n", eol) if eol == "\r\n" else replace
        tail_no_nl = (b == n and not final_nl)
        if tail_no_nl and new_mid.endswith(eol):
            new_mid = new_mid[: -len(eol)]
        expected = "".join(with_ends[:a]) + new_mid + "".join(with_ends[b:])
        if oc[0].status != "applied":
            # replace-mode 'have' is allowed only when the replacement is present and distinctive
            assert oc[0].status == "have", (text, search, replace, oc[0])
            continue
        assert out == expected, (repr(text), repr(search), repr(replace), repr(out), repr(expected))
        checked += 1
    assert checked > 1500


def build_reply(rng, blocks):
    parts = []
    if rng.random() < 0.5:
        parts.append("Here is my plan.\n\n")
    for kind, path, a, b in blocks:
        if kind == "edit":
            fence = rng.random() < 0.4
            parts.append(f"### EDIT: {path}\n" + ("```python\n" if fence else "")
                         + f"<<<<<<< SEARCH\n{a}=======\n{b}>>>>>>> REPLACE\n" + ("```\n" if fence else "")
                         + ("\n" if rng.random() < 0.5 else ""))
        else:
            parts.append(f"### FILE: {path}\n````python\n{a}````\n\n")
        if rng.random() < 0.2:
            parts.append("Some prose between blocks.\n\n")
    parts.append("### END CHANGES\n\nBETTER IDEA? None.\n")
    return "".join(parts)


def rand_body(rng):
    return "".join(x + "\n" for x in rand_lines(rng, rng.randint(1, 5)) if x not in ("=====",))


def test_parser_roundtrip_and_truncation_safety():
    """(1) Every rendered reply parses back to exactly its blocks.
    (2) Cut the reply at EVERY character: whatever is staged is always an
    exact, complete original block - never a partial one - and if anything is
    missing, the parser reports an error or the END marker is absent."""
    rng = random.Random(99)
    for trial in range(120):
        blocks = []
        for i in range(rng.randint(1, 4)):
            kind = rng.choice(["edit", "edit", "file"])
            body_a = rand_body(rng).replace("```", "``")
            body_b = rand_body(rng).replace("```", "``")
            blocks.append((kind, f"pkg/m{trial}_{i}.py", body_a, body_b))
        reply = build_reply(rng, blocks)
        pr = K.parse_changes(reply)
        assert not pr.errors, (reply, pr.errors)
        got = [(b.kind, b.path, (b.edit.search, b.edit.replace) if b.edit else b.content) for b in pr.blocks]
        want = [(k, p, (a, b) if k == "edit" else a) for k, p, a, b in blocks]
        assert got == want
        originals = set(want)
        for cut in range(0, len(reply), max(1, len(reply) // 400)):
            prc = K.parse_changes(reply[:cut])
            staged = [(b.kind, b.path, (b.edit.search, b.edit.replace) if b.edit else b.content)
                      for b in prc.blocks]
            for s in staged:
                assert s in originals, ("PARTIAL BLOCK STAGED", cut, s)
            if len(staged) < len(want):
                assert prc.errors or not prc.end_marker, cut


def test_transaction_random_failures_never_half_apply(tmp_path):
    rng = random.Random(7)
    for trial in range(40):
        root = tmp_path / f"AA{trial}"
        root.mkdir()
        files = {}
        for i in range(rng.randint(2, 6)):
            data = render(rand_lines(rng, rng.randint(3, 12)), rng.choice(["lf", "crlf"]), rng, True)
            data = f"marker_{i} = {i}\n" + data
            (root / f"f{i}.py").write_bytes(data.encode())
            files[f"f{i}.py"] = data
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        props = [K.Proposal(raw_path=n, kind="edit",
                            edits=[K.EditBlock(f"marker_{i} = {i}\n", f"marker_{i} = {i + 100}\n", 1)])
                 for i, n in enumerate(files)]
        fail_at = rng.randint(1, len(files))
        calls = {"n": 0}

        def flaky(path, data, keep=None):
            calls["n"] += 1
            if calls["n"] == fail_at:
                raise OSError("disk full")
            K.write_bytes_atomic(path, data, keep)

        ap = K.Applier(root, root / ".kimi_backups", K.ApplyOptions(skip_checks=True))
        with pytest.raises(K.ApplyAborted):
            with contextlib.redirect_stdout(io.StringIO()):
                ap.apply(ap.validate(props), {}, _write=flaky)
        after = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
        assert after == {k: v for k, v in before.items() if k in after} and set(after) == {
            k for k in before if (root / k).is_file()}


# =========================================================================
# END TO END: main() with a fake streaming API, then the real CLI
# =========================================================================
DRIVER = textwrap.dedent(r'''
    import os, sys, json
    from types import SimpleNamespace as NS
    sys.path.insert(0, os.environ["KIMICLI_DIR"])
    import kimicli as K

    REPLY = open(os.environ["FAKE_REPLY"], encoding="utf-8").read()
    FINISH = os.environ.get("FAKE_FINISH", "stop")

    def chunks():
        yield NS(choices=[NS(delta=NS(reasoning_content="thinking...", content=None), finish_reason=None)], usage=None)
        step = 37
        for i in range(0, len(REPLY), step):
            yield NS(choices=[NS(delta=NS(reasoning_content=None, content=REPLY[i:i + step]), finish_reason=None)], usage=None)
        yield NS(choices=[NS(delta=NS(reasoning_content=None, content=None), finish_reason=FINISH)], usage=None)
        u = NS(model_dump=lambda: {"prompt_tokens": 1000, "completion_tokens": 200, "cached_tokens": 900})
        yield NS(choices=[], usage=u)

    class FakeCompletions:
        def create(self, **kw):
            assert kw["stream"] is True and "temperature" not in kw
            return chunks()

    def fake_init(self, api_key, base_url, timeout=0):
        self.client = NS(chat=NS(completions=FakeCompletions()))
        self.api_key, self.base_url = api_key, base_url
    K.Kimi.__init__ = fake_init
    K.Kimi.balance = lambda self: {"available_balance": 50.0, "voucher_balance": 0, "cash_balance": 50.0}
    K.Kimi.count_tokens = lambda self, m, model: None
    K.API_KEY = "sk-test"
    sys.argv = ["kimicli.py"] + json.loads(os.environ["ARGS"])
    sys.exit(K.main())
''')


def run_main(repo: Path, args, reply: str, finish: str = "stop"):
    (repo / "reply.txt").write_text(reply, encoding="utf-8")
    env = dict(os.environ, KIMICLI_DIR=str(KIMI_DIR), KIMI_PROJECT_ROOT=str(repo),
               FAKE_REPLY=str(repo / "reply.txt"), FAKE_FINISH=finish, ARGS=json.dumps(args),
               MOONSHOT_API_KEY="sk-test", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-c", DRIVER], cwd=repo, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)


def cli(repo: Path, *args):
    env = dict(os.environ, KIMI_PROJECT_ROOT=str(repo), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(KIMI_DIR / "kimicli.py"), *args], cwd=repo, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120, input="y\n")


def mk(tmp_path):
    repo = tmp_path / "AA"
    (repo / "packages/auto_apply/src/auto_apply").mkdir(parents=True)
    (repo / "packages/auto_apply/src/auto_apply/__init__.py").write_text("")
    (repo / "packages/auto_apply/src/auto_apply/core.py").write_bytes(
        b"import os\r\n\r\n\r\ndef answer():\r\n    return 41\r\n")
    (repo / "dump.txt").write_text("\n---\nFile: AA/packages/auto_apply/src/auto_apply/core.py\n---\n"
                                   "import os\n\n\ndef answer():\n    return 41\n")
    return repo


GOOD = ("Ruling first.\n\nFiles:\n- packages/auto_apply/src/auto_apply/core.py - EDIT - fix the answer\n\n"
        "### EDIT: AA/packages/auto_apply/src/auto_apply/core.py\n<<<<<<< SEARCH\ndef answer():\n    return 41\n"
        "=======\ndef answer():\n    return 42\n>>>>>>> REPLACE\n\n### END CHANGES\n\nBETTER IDEA? None.\n")


def test_full_loop(tmp_path):
    repo = mk(tmp_path)
    original = (repo / "packages/auto_apply/src/auto_apply/core.py").read_bytes()
    r = run_main(repo, ["--prompt", "fix it", "--request-code", "--codebase", str(repo / "dump.txt"),
                        "--no-todo", "-y", "--no-count"], GOOD)
    assert r.returncode == 0, r.stdout + r.stderr
    tail = r.stdout.strip().splitlines()[-6:]
    assert any("--apply-fixes" in ln and "--dry-run" in ln for ln in tail), r.stdout[-1500:]
    sid = [d.name for d in (repo / ".kimi_out").iterdir() if d.is_dir()][0]
    sdir = repo / ".kimi_out" / sid
    assert (sdir / "reply_turn1.md").read_text(encoding="utf-8") == GOOD
    assert "### END CHANGES" in (sdir / "transcript.md").read_text(encoding="utf-8")
    assert (sdir / "preview_turn1.diff").read_text().count("+    return 42") == 1

    r = cli(repo, "--apply-fixes", sid, "--dry-run")
    assert r.returncode == 0 and "DRY RUN" in r.stdout, r.stdout
    assert (repo / "packages/auto_apply/src/auto_apply/core.py").read_bytes() == original

    r = cli(repo, "--apply-fixes", "last", "-y")
    assert r.returncode == 0, r.stdout
    assert (repo / "packages/auto_apply/src/auto_apply/core.py").read_bytes() == \
        b"import os\r\n\r\n\r\ndef answer():\r\n    return 42\r\n"

    r = cli(repo, "--history")
    assert "complete" in r.stdout

    r = cli(repo, "--undo", "last", "-y")
    assert r.returncode == 0 and "byte-for-byte" in r.stdout, r.stdout
    assert (repo / "packages/auto_apply/src/auto_apply/core.py").read_bytes() == original


def test_cut_off_reply_is_refused_and_repair_is_offered(tmp_path):
    repo = mk(tmp_path)
    cut = GOOD[: GOOD.index("=======") + 8]
    r = run_main(repo, ["--prompt", "fix it", "--request-code", "--codebase", str(repo / "dump.txt"),
                        "--no-todo", "-y", "--no-count"], cut, finish="length")
    assert "finish_reason=length" in r.stdout
    assert "NOT APPLICABLE" in r.stdout and "--resume" in r.stdout
    sid = [d.name for d in (repo / ".kimi_out").iterdir() if d.is_dir()][0]
    r = cli(repo, "--apply-fixes", sid, "-y")
    assert r.returncode == 1 and "NO FILES WERE MODIFIED" in r.stdout


def test_missing_prompt_file_is_not_sent(tmp_path):
    repo = mk(tmp_path)
    r = run_main(repo, ["--prompt", "e1_autonomy.md", "--no-todo", "-y", "--no-count"], GOOD)
    assert r.returncode == 1 and "Not sent" in r.stdout
    assert not any(d.is_dir() for d in (repo / ".kimi_out").iterdir())


def test_resume_with_repair_prompt(tmp_path):
    repo = mk(tmp_path)
    bad = GOOD.replace("    return 41\n=======", "    return 40\n=======")
    r = run_main(repo, ["--prompt", "fix it", "--request-code", "--codebase", str(repo / "dump.txt"),
                        "--no-todo", "-y", "--no-count"], bad)
    sid = [d.name for d in (repo / ".kimi_out").iterdir() if d.is_dir()][0]
    repair = repo / ".kimi_out" / sid / "repair_turn1.md"
    assert repair.exists() and "return 41" in repair.read_text()
    r = run_main(repo, ["--resume", sid, "--prompt", str(repair), "--request-code", "-y", "--no-count"], GOOD)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Every block resolves" in r.stdout
    r = cli(repo, "--apply-fixes", sid, "-y")
    assert r.returncode == 0, r.stdout
    assert b"return 42" in (repo / "packages/auto_apply/src/auto_apply/core.py").read_bytes()


def test_selftest_cli(tmp_path):
    repo = mk(tmp_path)
    r = cli(repo, "--selftest")
    assert r.returncode == 0 and " passed." in r.stdout and "FAIL" not in r.stdout, r.stdout