---
title: "ADR-018: Layered Settings Disclosure and the Per-User Motion Profile"
status: needs-review
last_verified: 2026-10-05
verified_against: "profile.py ApplicationConfig, registry.py _merge_config, settings_editor.py Browser tab, profile_wizard.py behaviour question"
audience: contributors
---

# ADR-018: Layered Settings Disclosure and the Per-User Motion Profile

**Status:** Accepted
**Date:** 2026-10-05
**Deciders:** Nicholas Liebmann
**Supersedes / Superseded by:** none

## Context

Four measured defects prompted this, all in the pointer/scroll behaviour
settings:

1. **The GUI lied.** "Enable Human Behavior Simulation" (with the note "Adds
   random pauses and mouse movements") wrote `enable_behavior_humanization`,
   whose only runtime consumer is `use_stealth_driver` in
   `registry.py` — undetected-chromedriver eligibility. Actual motion is
   governed by the `motion:` section, which no surface exposed.
2. **The defaults disagreed.** Profile default `False`, registry fallback
   `True`, CLI wizard `True` — a GUI-made profile silently disabled the
   stealth driver while its label implied the opposite.
3. **The admin lock was coarse.** Motion could only be locked by replacing
   the entire `motion` section through `config_overrides`, and
   `docs/user_guide/admin_policy.md` documented no way to do it.
4. **There was no per-user choice.** The `motion:` section lived only in
   `runtime_defaults.yaml` (app-wide), so a USB drive carrying two profiles
   could not give them different behaviour.

There is also a standing design tension, named by the project owner: AA's
customisation should be *vast*, but most of AA's users are general users —
library and workforce-centre patrons, people new to computers, people under
stress — for whom vast customisation is a hazard, while engineers and
researchers need every value within reach.

## Decision

**Layered settings disclosure.** Every configurable concept is presented in
layers, and each user sees only as much as they need:

- **Layer 0 (everyone):** a small set of plain-language named choices,
  validated by the domain model at edit time with refusals in the user's
  words. Both surfaces (GUI and CLI) offer the same choices and write the
  same field.
- **Layer 1 (comfortable):** honestly-named toggles for consequential
  switches. Risky switches carry their consequence in the label and are
  never one accidental click away.
- **Layer 2 (engineer/researcher):** every value, reached through validated
  configuration (`app_config.motion_overrides` in the profile JSON), with
  the resolved result inspectable (`--check-config`).

The motion settings are the first concept built on this pattern:

- `ApplicationConfig.motion_profile` — `"human" | "careful" | "instant"` or
  `None` (inherit). Validated by a pydantic field_validator whose message
  names the choices; `validate_assignment=True` means the GUI save path and
  profile load both run it.
- `ApplicationConfig.motion_overrides` — per-field overrides, validated by
  the *same* `MotionConfig.from_mapping` the session is validated with, so
  there is exactly one validator and one set of ranges. They are checked
  against the profile the user chose (or, when unset, re-checked against
  the app-wide default at session build).
- The merge follows the existing input → resolution → resolved precedent in
  `CapabilitiesRegistry._merge_config` (the browser pick): the profile emits
  flat declarative inputs; the merge folds them into the nested `motion`
  section and drops the flat keys, so the two names cannot drift.
- `AdminPolicy.motion_profile` is a field-level lock, applied after
  `config_overrides` so the named lock wins, and shown as locked (disabled,
  lock icon) in the settings UI. A lock is a lock in full: the user's
  `motion_profile` and `motion_overrides` are both ignored while it holds,
  so per-value overrides cannot retune the locked profile.
- `enable_behavior_humanization` keeps its name (schema stability) but its
  GUI label now says what it does, and its default is aligned with the
  registry fallback (`True`).
- Profile names live exactly once: `MOTION_PROFILE_NAMES` in
  `domain/models/motion_profile.py`.

## Options considered

- **Rename the field to `enable_stealth_driver` with a validation alias.**
  Rejected for this change: the honesty defect was in the UI label, which is
  fixed; a schema rename ripples through readers and unseen tests for no
  behaviour gain. Recorded as a possible future cleanup.
- **A per-run CLI flag.** Rejected: behaviour is a persistent user
  preference, and a transient flag is a second, diverging write path that
  breaks GUI/CLI parity by construction.
- **Expose all ~25 MotionProfile fields in the GUI now.** Rejected: it is
  exactly the wall-of-knobs the layered pattern exists to avoid, and layer 2
  already reaches every value through validated config. A future GUI
  "advanced" section should follow this ADR's pattern.
- **Admin lock only via `config_overrides`.** Rejected: replacing the whole
  section to lock one value is coarse, invisible in the UI, and
  undocumented.

## Consequences

- Easier: users get a truthful, three-choice control; engineers reach every
  value with early, plain-word validation; admins get a documented,
  field-level lock; `--check-config` shows the resolved values.
- Harder: two new profile fields and one new policy field to maintain; the
  pattern's second consumer does not exist yet (this is the test case).
- **Behaviour changes (disclosed):** profiles lacking
  `enable_behavior_humanization` now default it to `True` (aligning with the
  registry fallback and the wizard); the wizard always writes
  `app_config.motion_profile`.
- Migration: none. Old profiles and old policy files load unchanged (new
  fields default to `None` = inherit / no lock), pinned by tests.
- The research record of how AA acted (session tally, `submit_rung`) lives
  in the SessionReport. Ingestion into the consent-gated research database
  is deferred: it needs a schema version bump and consent-text review, which
  is its own stage.

## References

- `src/auto_apply/domain/models/profile.py` — `ApplicationConfig.motion_profile`,
  `motion_overrides`, validators; `UserProfile.settings` emission.
- `src/auto_apply/infrastructure/registry.py` — `_merge_config` motion fold.
- `src/auto_apply/domain/models/policy.py` — `AdminPolicy.motion_profile`.
- `src/auto_apply/adapters/primary/gui/settings_editor.py` — Browser tab
  combobox, lock display, inheritance-preserving save.
- `src/auto_apply/adapters/primary/cli/profile_wizard.py` — behaviour
  question and repair handler.
- `tests/application/test_motion_settings.py` — the pins.
- [ADR-017](017_documentation_gate.md) — the gate this record lands under.
- [Admin Policy](../user_guide/admin_policy.md) — the documented lock.
- [Profile Format Reference](../reference/profile_schema.md) — the fields.
