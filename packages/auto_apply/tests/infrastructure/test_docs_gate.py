"""Gate 5: the documentation gate.

AA's defining defect class is capability that was built and never connected.
The documentation form of that defect is a page describing intent as
achievement, and it is not caused by careless writing -- it is caused by the
code changing while the page does not.

Measured on 2026-09-19, before this file existed: 0 of 65 pages carried a
status marker, 3 of 65 recorded when they were last checked, two documented
install commands named an extra that does not exist, 11 relative links were
broken, 8 documents described retired modules as live, 20 of 55 pages were
unreachable from the site navigation, two of four real CI gates were
undocumented, and one page ended with a chat-transcript sign-off committed
verbatim.

Three separate documentation programmes had been written before this one and
none was ever committed. Writing better documents had a measured zero percent
landing rate, so the remedy is not another document -- it is a pin, on the same
terms as every other invariant in AA. See docs/adr/017_documentation_gate.md.

The precedent is tests/infrastructure/test_install_commands_exist.py, which has
caught documentation defects in three files since 2026-09-05. This file widens
that idea to the whole tree; check 4 below deliberately subsumes and extends
its extras check, because the older pin scans exactly three files and docs/ was
outside its scan set.

WHAT THIS PIN CANNOT CATCH: whether a true-looking sentence is true. It checks
structural currency and internal consistency only. Correctness needs a human
reading the code, which is what the `last_verified` field records and why it is
mandatory.

Standard library only, and no network. This must run on the 3.10 floor.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import pytest

_INFRA_DIR = Path(__file__).resolve().parent            # .../tests/infrastructure
_PACKAGE_DIR = _INFRA_DIR.parent.parent                 # .../packages/auto_apply
_REPO_ROOT = _PACKAGE_DIR.parent.parent                 # .../AA

DOCS_DIR = _PACKAGE_DIR / "docs"
RETIRED_DIR = DOCS_DIR / "old_retired_files"
MKDOCS = _PACKAGE_DIR / "mkdocs.yml"
ADR_DIR = DOCS_DIR / "adr"
ADR_INDEX = ADR_DIR / "index.md"
STATUS = DOCS_DIR / "STATUS.md"
CITATION = _REPO_ROOT / "CITATION.cff"
PACKAGE_PYPROJECT = _PACKAGE_DIR / "pyproject.toml"

# Front matter is required on docs/ pages. These two are excluded by intent:
# the retirement ledger is an index of retired files rather than a documentation
# page, and anything inside old_retired_files/ is a historical artefact that
# must not be edited (retire.py stamps line 1, so front matter cannot be first).
FRONT_MATTER_EXEMPT = {
    RETIRED_DIR / "README.md",
}

REQUIRED_FRONT_MATTER = ("title", "status", "last_verified", "audience")
VALID_STATUS = {"reviewed", "needs-review", "superseded"}

_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_FM_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:", re.MULTILINE)
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_EXTRA = re.compile(r"auto_apply\[([^\]]+)\]")
_BARE_KEY = re.compile(r"^([A-Za-z0-9_-]+)\s*=", re.MULTILINE)
_VERSION = re.compile(r'^version\s*[:=]\s*"?([0-9][^"\s]*)"?', re.MULTILINE)

# Detection patterns. These phrases appear when a chat transcript is pasted
# into a document instead of prose written for it; one of them shipped in
# docs/index.md for months. They are a banned-phrase list, like any linter's --
# the strings must stay literal for the check to match.
_CONVERSATIONAL_RESIDUE = (
    "i can now move on",
    "just tell me where you want to go",
    "let me know if you",
    "would you like me to",
    "i've created the",
    "shall i continue",
    "as an ai language model",
    "here is the complete file",
)


def _docs_pages() -> list[Path]:
    """Every Markdown page under docs/, excluding the retirement directory."""
    return sorted(
        p for p in DOCS_DIR.rglob("*.md")
        if RETIRED_DIR not in p.parents and p != RETIRED_DIR
    )


def _all_markdown() -> list[Path]:
    """Every Markdown file in the repository that we own."""
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.md"):
        parts = set(path.parts)
        # Hidden directories hold virtualenvs, caches, version-control
        # internals and local tooling output. None of that is project
        # documentation, and scanning it raises failures on files nobody
        # ships. `.github` is the deliberate exception: its issue and
        # pull-request templates are real, committed project files.
        if any(part.startswith(".") and part != ".github" for part in path.parts):
            continue
        if parts & {"node_modules", "__pycache__", "site", "htmlcov",
                    "build", "dist"}:
            continue
        if RETIRED_DIR in path.parents:
            continue
        out.append(path)
    return sorted(out)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _front_matter(text: str) -> dict[str, str] | None:
    match = _FRONT_MATTER.match(text)
    if match is None:
        return None
    block = match.group(1)
    found: dict[str, str] = {}
    for key_match in _FM_KEY.finditer(block):
        key = key_match.group(1)
        rest = block[key_match.end():].split("\n", 1)[0].strip()
        found[key] = rest.strip('"').strip("'")
    return found


def _declared_extras() -> set[str]:
    """Extras declared in the package manifest.

    A structural reader, not a TOML parser: tomllib is stdlib only from 3.11
    and AA's floor is 3.10. Same approach as test_install_commands_exist.py.
    """
    text = _read(PACKAGE_PYPROJECT)
    start = text.find("[project.optional-dependencies]")
    assert start != -1, "packages/auto_apply/pyproject.toml declares no extras"
    end = text.find("\n[", start + 1)
    block = text[start:] if end == -1 else text[start:end]
    return set(_BARE_KEY.findall(block))


# --------------------------------------------------------------------------
# 1. Provenance front matter
# --------------------------------------------------------------------------

def test_every_docs_page_carries_provenance_front_matter() -> None:
    """A claim's age is part of its content.

    Before this pin, 3 of 65 pages recorded any date at all, so a reader could
    not tell a current page from one that had drifted for a year.
    """
    problems: list[str] = []
    today = _dt.date.today()

    for page in _docs_pages():
        if page in FRONT_MATTER_EXEMPT:
            continue
        rel = page.relative_to(_REPO_ROOT).as_posix()
        front = _front_matter(_read(page))

        if front is None:
            problems.append(f"{rel}: no YAML front matter block")
            continue

        for key in REQUIRED_FRONT_MATTER:
            if key not in front:
                problems.append(f"{rel}: front matter is missing '{key}'")

        status = front.get("status")
        if status is not None and status not in VALID_STATUS:
            problems.append(
                f"{rel}: status '{status}' is not one of {sorted(VALID_STATUS)}"
            )

        raw_date = front.get("last_verified")
        if raw_date is not None:
            try:
                parsed = _dt.date.fromisoformat(raw_date)
            except ValueError:
                problems.append(
                    f"{rel}: last_verified '{raw_date}' is not an ISO date (YYYY-MM-DD)"
                )
            else:
                if parsed > today:
                    problems.append(
                        f"{rel}: last_verified {raw_date} is in the future"
                    )

    assert not problems, (
        "Documentation pages are missing provenance front matter.\n"
        "Every page under docs/ needs title, status, last_verified and audience.\n"
        "See docs/DOCUMENTATION_STANDARDS.md section 3.\n\n  "
        + "\n  ".join(problems)
    )


# --------------------------------------------------------------------------
# 2. Links resolve
# --------------------------------------------------------------------------

def test_every_relative_link_resolves() -> None:
    """11 links were broken before this pin, including the Architecture Bible
    linked from both READMEs at a path it has never occupied.
    """
    broken: list[str] = []

    for path in _all_markdown():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for target in _LINK.findall(_read(path)):
            if target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
                continue
            bare = target.split("#", 1)[0].strip()
            if not bare:
                continue
            resolved = (path.parent / bare).resolve()
            if not resolved.exists():
                broken.append(f"{rel} -> {target}")

    assert not broken, (
        "Broken relative links. Fix the link or the target, in this change:\n\n  "
        + "\n  ".join(broken)
    )


# --------------------------------------------------------------------------
# 3. No document describes a retired module as if it were live
# --------------------------------------------------------------------------

def test_no_document_references_a_retired_module() -> None:
    """For eleven days, eight documents advertised the zero-browser static path
    after its three implementation files had been retired.

    A retired file may be *named* -- ADRs and the ledger must be able to discuss
    it -- but only in a document that also says it is retired.
    """
    if not RETIRED_DIR.exists():
        pytest.skip("no retirement directory in this checkout")

    retired_names = {
        p.name for p in RETIRED_DIR.rglob("*")
        if p.is_file() and p.suffix in {".py", ".sh", ".bat"} and p.name != "README.md"
    }
    if not retired_names:
        pytest.skip("retirement directory is empty")

    # The acknowledgement is the retirement directory itself, not merely the
    # word "retired". "Retired" is ordinary English: one unrelated sentence
    # anywhere in a long document used to hand that whole document a blanket
    # exemption to name any retired module as though it were live. A document
    # that legitimately discusses a retired module says where it went.
    # Measured: all six documents that name one already carry this literal,
    # so this is strictly tighter with no false positives.
    acknowledging = ("old_retired_files",)
    offenders: list[str] = []

    for path in _all_markdown():
        text = _read(path)
        lowered = text.lower()
        if any(word in lowered for word in acknowledging):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for name in sorted(retired_names):
            if name in text:
                offenders.append(f"{rel} names '{name}' without saying it is retired")

    assert not offenders, (
        "Documents describe retired modules as if they were live.\n"
        "Either remove the reference or state that the module is retired.\n\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# 4. Documented extras exist
# --------------------------------------------------------------------------

def test_every_documented_extra_is_declared() -> None:
    """An extra named "full" was documented in two places and has never existed.

    test_install_commands_exist.py would have caught it, but scans exactly
    three files and docs/ is outside its scan set. This check covers the tree.
    """
    declared = _declared_extras()
    problems: list[str] = []

    for path in _all_markdown():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for group in _EXTRA.findall(_read(path)):
            for extra in (part.strip() for part in group.split(",")):
                if extra and extra not in declared:
                    problems.append(
                        f"{rel}: documents auto_apply[{extra}], "
                        f"which is not declared. Declared: {sorted(declared)}"
                    )

    assert not problems, "Documented install extras do not exist.\n\n  " + "\n  ".join(
        dict.fromkeys(problems)
    )


# --------------------------------------------------------------------------
# 5. The ADR register and the directory agree
# --------------------------------------------------------------------------

def test_adr_index_and_directory_agree() -> None:
    """The index once listed twelve records, summarised ten, and offered a
    template telling contributors to create 011 -- which already existed.
    """
    index_text = _read(ADR_INDEX)
    on_disk = {
        p.name for p in ADR_DIR.glob("*.md") if p.name != "index.md"
    }
    listed = set(re.findall(r"\(([0-9]{3}_[A-Za-z0-9_]+\.md)\)", index_text))

    missing_from_index = sorted(on_disk - listed)
    missing_from_disk = sorted(listed - on_disk)

    assert not missing_from_index, (
        "ADR files exist but are not listed in docs/adr/index.md: "
        f"{missing_from_index}"
    )
    assert not missing_from_disk, (
        "docs/adr/index.md links ADRs that do not exist: " f"{missing_from_disk}"
    )


def test_adr_numbers_are_unique() -> None:
    numbers: dict[str, list[str]] = {}
    for path in ADR_DIR.glob("*.md"):
        if path.name == "index.md":
            continue
        numbers.setdefault(path.name[:3], []).append(path.name)
    duplicates = {n: f for n, f in numbers.items() if len(f) > 1}
    assert not duplicates, f"Two ADRs share a number: {duplicates}"


# --------------------------------------------------------------------------
# 6. Every page is reachable from the site
# --------------------------------------------------------------------------

def test_every_docs_page_is_in_the_mkdocs_nav() -> None:
    """20 of 55 pages were unreachable from the built site, including all
    twelve ADRs, the Architecture Bible and the engineering philosophy.

    Read as text rather than parsed as YAML: mkdocs.yml uses a
    `!!python/name:` tag that a plain yaml.safe_load rejects, and this pin must
    not require PyYAML to agree with MkDocs about custom tags.
    """
    nav_text = _read(MKDOCS)
    missing = [
        page.relative_to(DOCS_DIR).as_posix()
        for page in _docs_pages()
        if page.relative_to(DOCS_DIR).as_posix() not in nav_text
    ]
    assert not missing, (
        "Pages exist under docs/ but are unreachable from the site navigation.\n"
        "Add them to packages/auto_apply/mkdocs.yml in this change:\n\n  "
        + "\n  ".join(missing)
    )


def test_mkdocs_nav_has_no_dangling_entries() -> None:
    # Comments are stripped before scanning. A YAML comment may legitimately
    # name a page -- the exclude_docs block explains which retired documents it
    # keeps out of the built site -- and a comment is documentation about the
    # configuration, not a navigation entry. Measured: without this, the pin
    # failed on its own explanation.
    body = "\n".join(line.split("#", 1)[0] for line in _read(MKDOCS).splitlines())
    referenced = set(re.findall(r"([A-Za-z0-9_/\-]+\.md)", body))
    dangling = sorted(t for t in referenced if not (DOCS_DIR / t).exists())
    assert not dangling, f"mkdocs.yml navigation points at missing pages: {dangling}"


# --------------------------------------------------------------------------
# 7. Citation metadata agrees with the package manifest
# --------------------------------------------------------------------------

def test_citation_version_matches_the_package_version() -> None:
    """CITATION.cff said 1.0.0-alpha while pyproject said 0.1.0.

    A citation cannot be resolved against a version that was never tagged.
    """
    citation = _VERSION.search(_read(CITATION))
    assert citation is not None, "CITATION.cff declares no version"

    pyproject_text = _read(PACKAGE_PYPROJECT)
    start = pyproject_text.find("[project]")
    assert start != -1, "packages/auto_apply/pyproject.toml has no [project] table"
    end = pyproject_text.find("\n[", start + 1)
    block = pyproject_text[start:] if end == -1 else pyproject_text[start:end]
    package = _VERSION.search(block)
    assert package is not None, "packages/auto_apply/pyproject.toml declares no version"

    assert citation.group(1) == package.group(1), (
        "CITATION.cff and packages/auto_apply/pyproject.toml disagree about the "
        f"version: {citation.group(1)!r} vs {package.group(1)!r}"
    )


def test_citation_cff_has_no_empty_pattern_bearing_fields() -> None:
    """TEETH (item 10, B2): measured 2026-10-02 with cffconvert --validate
    against CFF 1.2.0: `doi: ""` fails the DOI pattern and `orcid: ""` fails
    the ORCID pattern — a Zenodo deposit from the file would fail or be
    wrong. An empty value in a pattern-bearing field is worse than an absent
    key: absent is valid. Also asserts the keys CFF 1.2.0 requires are
    present. This is the offline half of cffconvert --validate; the full
    schema check needs the network and stays out of the gate.
    """
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(_read(CITATION))
    assert isinstance(data, dict), "CITATION.cff is not a parseable mapping"

    for key in ("cff-version", "title", "message", "authors", "version", "license"):
        assert data.get(key) not in (None, ""), (
            f"CITATION.cff: required key {key!r} is missing or empty"
        )

    pattern_bearing = frozenset({
        "doi", "orcid", "url", "repository", "repository-code",
        "repository-artifact", "email", "date-released",
    })
    problems: list[str] = []

    def _walk(node: object, path: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key in pattern_bearing
                    and isinstance(value, str)
                    and not value.strip()
                ):
                    problems.append(
                        f"{path}{key}: empty string — delete the key; absent "
                        "is valid, empty is not"
                    )
                _walk(value, f"{path}{key}.")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                _walk(item, f"{path}{index}.")

    _walk(data)
    assert not problems, "CITATION.cff has empty pattern-bearing fields.\n\n  " + "\n  ".join(
        problems
    )


# --------------------------------------------------------------------------
# 8. No conversational residue
# --------------------------------------------------------------------------

def test_no_conversational_residue() -> None:
    """docs/index.md ended with a chat-transcript sign-off, committed verbatim:
    "I can now move on to any specific file you'd like fleshed out next."
    """
    offenders: list[str] = []
    for path in _all_markdown():
        lowered = _read(path).lower()
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for phrase in _CONVERSATIONAL_RESIDUE:
            # This file quotes the phrases in order to check for them.
            if phrase in lowered:
                offenders.append(f"{rel}: contains {phrase!r}")
    assert not offenders, (
        "Conversational text was committed into a document:\n\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# 9. Readiness is asserted in exactly one place
# --------------------------------------------------------------------------

def test_readiness_is_claimed_only_in_status() -> None:
    """Readiness was once asserted in four places that disagreed, and the docs
    home page marked six subsystems 'Stable' -- including a form-filling engine
    that had never completed a submission.
    """
    marker = re.compile(r"\|\s*(?:✅|\u2705)?\s*Stable\s*\|", re.IGNORECASE)
    offenders = [
        page.relative_to(_REPO_ROOT).as_posix()
        for page in _docs_pages()
        if page != STATUS and marker.search(_read(page))
    ]
    assert not offenders, (
        "Readiness tables belong in docs/STATUS.md and nowhere else.\n"
        "Link to STATUS.md instead of restating it:\n\n  " + "\n  ".join(offenders)
    )


def test_status_page_exists_and_is_current() -> None:
    assert STATUS.exists(), "docs/STATUS.md is the single source of readiness truth"
    front = _front_matter(_read(STATUS))
    assert front is not None and "last_verified" in front, (
        "docs/STATUS.md must record when it was last verified"
    )
