---
title: Port Catalogue
status: reviewed
last_verified: 2026-09-19
verified_against: "src/auto_apply/domain/ports/ — 35 modules, importer counts measured"
audience: contributors
---

# Port Catalogue

Every capability AA needs from the outside world is a **port** in
`domain/ports/`. Adapters implement them; the composition root wires them. A
port is AA's extension point — there is no plugin framework, no entry-point
scanning and no lifecycle hooks, because the hexagon already provides the seam
([ADR-008](../adr/008_plugin_architecture.md)).

**Importers** below counts modules under `src/` that reference the port. Zero is
not automatically a defect — a port may be satisfied structurally, or may be a
named seam for a deferred capability — but **zero importers is always a question
worth answering**, and that is why the column is here.

## Driving ports

Through these, the outside world asks AA to do something.

| Port module | Protocols | Importers | Purpose |
| --- | --- | --- | --- |
| `ui_port.py` | `UIPort` | 0 | The UI-to-backend interface. Zero is expected today: both surfaces still import `SessionController` directly, carried as a WIRE-LATER exemption ([ADR-014](../adr/014_typed_ui_port.md)) |

## Driven ports

Through these, AA asks the outside world for something.

### Browser and interaction

| Port module | Protocols | Importers | Purpose |
| --- | --- | --- | --- |
| `browser_port.py` | `ElementInterface`, `BrowserInterface` | 51 | Framework-agnostic browser automation. The most-used port in AA |
| `browser_provider_port.py` | `DriverProvider` | 1 | The contract every driver factory satisfies |
| `interaction_port.py` | `InteractionPort` | 4 | Browser interaction operations |
| `interaction_primitives_port.py` | `PageActionPrimitives`, `PageNavigationPort`, `DomReadinessPort` | 0 | Narrow protocols for the two collaborators a form handler may touch |
| `navigation_port.py` | `InterruptionHandlerPort`, `NullInterruptionHandler` | 2 | Clearing whatever stands between a page and its content |
| `raw_driver_port.py` | `SupportsRawDriver`, `SupportsRawPage` | 0 | Escape hatch for framework-specific handles. Deliberately narrow and deliberately rare |

### Perception and reasoning

| Port module | Protocols | Importers | Purpose |
| --- | --- | --- | --- |
| `perception_port.py` | `PerceptionPort` | 4 | Reading and classifying page state |
| `math_perception_port.py` | `MathematicalPerceptionPort` | 3 | Extracting a mathematical DOM tree from a browser |
| `math_reasoning_port.py` | `FormUnderstandingPort` | 2 | Mathematical webpage understanding |
| `page_understanding_port.py` | `CardResolutionState`, `JobUrlCandidate`, `JobUrlRejection` | 11 | The intended home for the Math subsystem's capabilities |
| `page_classification_port.py` | `PageClassifierPort` | 0 | Deciding what kind of page is currently shown |
| `serp_extraction_port.py` | `SerpExtractionPort` | 0 | Turning a loaded results page into job listings |
| `reasoning_port.py` | `ILogicSolver`, `ReasoningPort` | 1 | Formal logic and reasoning engines |
| `text_similarity_port.py` | `TextSimilarityPort` | 3 | Text similarity scoring |
| `text_generation_port.py` | `TextGenerationPort` | 0 | Local open-ended text generation. A seam for the optional LLM tier |
| `accessibility_port.py` | `IAccessibilityNode`, `IAccessibilityScanner` | 3 | Accessibility Object Model interactions |

### Discovery

| Port module | Protocols | Importers | Purpose |
| --- | --- | --- | --- |
| `discovery_port.py` | `DiscoveryProviderPort` | 2 | Job discovery providers |
| `ats_port.py` | `ATSRegistryPort`, `ATSDescriptor`, `ATSPort` | 2 | ATS platform identification, backed by YAML descriptors ([ADR-004](../adr/004_ats_platform_registry.md)) |
| `resolution_port.py` | `ResolutionInterface` | 1 | Specialised URL-resolution engines |
| `location_port.py` | `LocationRepositoryPort`, `DistanceCalculatorPort` | 2 | Offline geospatial lookups and distance |

### Persistence

| Port module | Protocols | Importers | Purpose |
| --- | --- | --- | --- |
| `repository_port.py` | `Repository`, `JobRepositoryPort` | 3 | General data persistence |
| `profile_repository_port.py` | `ProfileRepositoryPort` | 6 | Profile persistence, shaped as the GUI needs it |
| `work_queue_port.py` | `WorkQueuePort` | 3 | The persistent priority task queue |
| `consent_repository_port.py` | `ConsentRepositoryPort` | 2 | Research-consent records |
| `feedback_repository_port.py` | `FeedbackRepositoryPort` | 2 | Page-analysis feedback |
| `audit_port.py` | `AuditSubmissionRecord`, `AuditRepositoryPort` | 1 | Correspondence-audit persistence |

### Control, policy and observation

| Port module | Protocols | Importers | Purpose |
| --- | --- | --- | --- |
| `registry_port.py` | `RegistryPort` | 5 | Reading the capabilities registry from the application layer |
| `environment_capabilities_port.py` | `EnvironmentCapabilitiesProvider` | 0 | Narrow read of detected environment capabilities |
| `interrupt_policy_port.py` | `Checkpoint`, `ApplicationContext`, `InterruptPolicy` | 3 | Human-in-the-loop decisions ([ADR-005](../adr/005_human_in_the_loop.md)) |
| `event_publisher_port.py` | `EventPublisherPort`, `NullEventPublisher` | 2 | Publish-only contract for components that emit but never consume |
| `extraction_observer_port.py` | `ExtractionObserverPort`, `PageAuditReporterPort`, `NullExtractionObserver` | 3 | Observer seams for extraction auditing |
| `health_monitor_port.py` | `HealthMonitor` | 0 | Background health monitors |
| `liveness_port.py` | `LivenessPort` | 2 | Polling whether a session is alive |
| `research_port.py` | `JobPostingObservation`, `FormObservation`, `ApplicationOutcomeObservation` | 7 | The contract between workflows and the research subsystem ([ADR-009](../adr/009_research_module.md)) |

---

## Rules

1. **A port is a contract, not a class.** Prefer `Protocol` and structural
   satisfaction over a base class the implementation must inherit.
2. **Ports live in the domain and import nothing from outside it.** An import of
   Selenium, SQLite or Tkinter in `domain/ports/` is a layer violation, asserted
   at an exact count by the architecture pin.
3. **Every port should have an adapter and a consumer.** INV-10. A port with
   neither is capability built and never connected — AA's defining defect.
4. **Every exemption is named and enumerated.** Exemption lists are **ceilings,
   not equalities**, and each entry carries its removal trigger, so an exemption
   cannot quietly become permanent.
5. **Retire, never delete.** `HTTPClientPort` was retired with its only
   implementation rather than removed, so the static-fetch capability can be
   recalled intact ([ADR-013](../adr/013_static_path_retirement.md)).

## Adding a port

1. Check `docs/old_retired_files/` first. The port may already exist, retired.
2. Write the `Protocol` in `domain/ports/`.
3. Write at least one adapter and one consumer **in the same change**. A port
   merged without both is an orphan by construction.
4. Wire it in the composition root — the only place that may know both sides.
5. If it changes a boundary or a guarantee, write an
   [ADR](../adr/index.md).
