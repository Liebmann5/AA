---
title: "Releasing AutoApply"
status: needs-review
last_verified: 2026-10-02
audience: contributors
---

# Releasing AutoApply

The numbered runbook for cutting one release, written for one person on
Windows. Every command is spelled out; run them in PowerShell from the
repository root unless a step says otherwise. `main` requires a pull
request, so the version bump and the DOI commit both go through one.

**Prerequisites** (once): the [GitHub CLI](https://cli.github.com/)
(`winget install GitHub.cli`), authenticated (`gh auth login`), and push
access to `Liebmann5/AA`.

What a release produces: the git tag, the GitHub release with the sdist and
wheel attached, two Sigstore attestations (one over the wheel and sdist, one
over the replay outputs) minted by the release workflow on GitHub's runners,
and — from the first release onward — a Zenodo deposit with a DOI.

## 1. Bump the version — in a PR

Edit both files on a branch — the documentation gate pins them equal, and
the release workflow refuses to publish if they disagree with the tag:

1. `packages/auto_apply/pyproject.toml` — `version = "0.1.0"` under
   `[project]` → the new version.
2. `CITATION.cff` — `version: "0.1.0"` → the same value, and set
   `date-released: "YYYY-MM-DD"` to today (the key is absent between
   releases on purpose; an empty value is invalid CFF).

```powershell
git checkout -b release/v0.1.0
git add packages/auto_apply/pyproject.toml CITATION.cff
git commit -m "release: v0.1.0"
git push -u origin release/v0.1.0
gh pr create --title "release: v0.1.0" --body "Version bump; gates green."
```

## 2. Run the gates locally

```powershell
cd packages/auto_apply
uv run pytest tests -q -p no:cacheprovider
uv run ruff check src --select F821 --output-format concise
uv run mypy --config-file ../../pyproject.toml src/auto_apply
uv run mypy --config-file ../../pyproject.toml --explicit-package-bases tests
cd ..\..
```

## 3. Merge and wait for CI

```powershell
gh pr checks --watch
gh pr merge --merge --delete-branch
git checkout main
git pull
gh run watch
```

Tag only a commit whose six CI legs are green. Merge with a merge commit,
never squash or rebase: the docs cite commit hashes, and a squash or rebase
rewrites them.

## 4. Tag

The tag name is `v` + the version, exactly — the release workflow strips
the `v` and compares the rest against both files:

```powershell
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

## 5. Publish the release

```powershell
gh release create v0.1.0 --title "v0.1.0" --notes "See CHANGELOG.md."
```

Publishing fires the **Release** workflow (`.github/workflows/release.yml`):

1. **versions** — fails the whole run if the tag, `pyproject.toml` and
   `CITATION.cff` disagree. Nothing is attested on a disagreement.
2. **replay** — replays the committed fixture corpus on GitHub's runner,
   requires byte-equality with the committed expected digest, and attests
   `replay.jsonl` and `manifest.json`.
3. **build** — builds the sdist and wheel (with `--out-dir dist`, so the
   artifacts land where the globs look), attests them, and uploads them
   to the release.

Watch it: `gh run watch`. If it fails, read the failing job's log with
`gh run view --log-failed`.

## 6. The one-time Zenodo switch

Do this **before the first release** (it is already done if a deposit
exists):

1. Sign in at <https://zenodo.org> with your GitHub account.
2. Go to <https://zenodo.org/account/settings/github/>.
3. Find `Liebmann5/AA` in the repository list and flip its toggle **ON**.

From then on, every published release deposits automatically; Zenodo reads
`CITATION.cff` for the metadata. There is deliberately no `.zenodo.json` —
CITATION.cff is the single source of metadata truth.

## 7. Add the DOI back — in a PR

After the first deposit exists:

1. Open the deposit on Zenodo and copy the **concept DOI** (the one Zenodo
   labels as citing *all versions*, of the form `10.5281/zenodo.<n>`).
2. On a branch, edit `CITATION.cff`: add `doi: "10.5281/zenodo.<n>"`.
3. ```powershell
   git checkout -b chore/citation-doi
   git add CITATION.cff
   git commit -m "citation: add Zenodo concept DOI"
   git push -u origin chore/citation-doi
   gh pr create --title "citation: add Zenodo concept DOI" --body "One-line metadata change."
   gh pr checks --watch
   gh pr merge --merge --delete-branch
   ```

**No second release is needed** — the concept DOI resolves to the latest
version and already covers the first one.

## 8. Verify the attestation

The wheel, with nothing but the GitHub CLI:

```powershell
gh release download v0.1.0 -R Liebmann5/AA -p "*.whl"
gh attestation verify auto_apply-0.1.0-py3-none-any.whl -R Liebmann5/AA
```

The replay outputs are deliberately NOT attached to the release. The
stronger check reproduces the attested digest on YOUR machine and verifies
those bytes:

```powershell
git clone --depth 1 --branch v0.1.0 https://github.com/Liebmann5/AA.git AA-verify
cd AA-verify
uv sync
cd packages/auto_apply
uv run python -m auto_apply --replay tests/fixtures/replay/corpus --replay-out replay_out
gh attestation verify replay_out/manifest.json -R Liebmann5/AA
```

`gh attestation verify` matches the local file's digest against the
attested subjects, so a match proves your machine reproduced the digest
the workflow attested on GitHub's.

## What a reader can and cannot conclude

- The **build attestation** proves the sdist and wheel were built from the
  tagged commit, by this repository's release workflow, on GitHub-hosted
  runners. It does not prove the code is correct.
- The **replay attestation** proves the committed corpus replays to the
  attested digest at that commit, computed on GitHub's machines — not only
  on the maintainer's. It says nothing about whether the corpus is
  representative.
- A **research bundle** (item 10, part A) proves its bytes left the
  exporting installation unaltered, under that installation's own key —
  when the bundle is signed. An installation with no signed rows has no
  key, and its bundle declares itself unsigned in `index.json` rather than
  minting one. Neither form proves the exporting code was unmodified, nor
  who the contributor is — compare the signing-key fingerprint with one
  the contributor published.

See [REPRODUCIBILITY.md](../REPRODUCIBILITY.md) for verifying research
bundles and replay output, and [STATUS.md](../STATUS.md) for what works.
