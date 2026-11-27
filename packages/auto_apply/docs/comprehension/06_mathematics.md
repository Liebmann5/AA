---
title: "Page Comprehension Toolkit: Mathematics"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Mathematics

Every algorithm below states: **definition → property → proof or sketch →
complexity → failure modes (returns, raises, hangs) → rejected alternatives →
three examples**. Example tags: **(R)** recorded in the repository's own evidence,
**(O)** observed live in pass 2 from a data centre (environment `cloud`, specimen IDs), **(K)** recalled public knowledge,
*unverified until the live set is frozen* ([09](09_verification.md)); class names are never relied on, only structure.
Every algorithm's worst case, adversarial inputs and tail budget are in [section 12](#12-worst-case-adversarial-inputs-and-tails);
its edge cases are catalogued in [12](12_edge_cases_and_adversity.md).

Conventions: `n` nodes in the `Doc`; `D` = relative-path depth cap (default 6);
`K` = record window cap (default 4, max 8); all thresholds are parameters in a
`ParameterSet` (CT-DS-007), shown here with their initial values `[GOAL]`.
Every loop is bounded by a **work-unit budget** (not wall time) so that a partial
result is reproducible on replay (CT-ALG-022).

## 1. Record segmentation (CT-ALG-001, 002, 003; tool CT-T-008)

**What is wrong today** `[WIRED]`, re-measured locally: two cards that differ only
by one extra CSS class get different `structural_hash` values (probe: `a==c` true,
`a==b` false), because the hash includes sorted classes (`math_dom.py:171-177`) —
contradicting the code's own rule that class names are never consulted
(`structural_hashing.py:39`). Grouping is then *exact equality of recursive
hashes*, so a promoted or selected card, or one extra badge anywhere in a subtree,
splits the group; the ranking key counts any non-tracking `data-*` anywhere below
a node, so it does not separate groups (defect 2).

**Definitions.** For element `v` and descendant `u` with `depth(u)-depth(v) ≤ D`,
the *relative label* of `u` is `λ(v,u) = (path of tag names from v to u,
has_href(u), has_own_text(u))`. Attributes and classes are excluded. The
*skeleton multiset* `M(v)` is the multiset of all `λ(v,u)`. Weighted Jaccard (Ruzicka)
similarity `J(A,B) = Σ min(A_i,B_i) / Σ max(A_i,B_i)` ∈ [0,1].

**Lemma 1 (metric).** `1-J` is a metric on multisets (the Soergel distance).
So similarity is symmetric, `J=1` iff the multisets are equal, and the triangle
inequality holds; "similar to a medoid" is therefore a meaningful cohesion test.

**Lemma 2 (tolerance).** If `|A| = s` and the multisets differ in total by `d`
(`Σ|A_i-B_i| = d < s`), then `J(A,B) ≥ (s-d)/s`. *Proof.* `Σmax = Σmin + d`, so
`J = Σmin/(Σmin+d)` is increasing in `Σmin`, and `Σmin ≥ s-d`. ∎ Consequence: a
card with 30 labels and a promoted variant adding 3 labels has `J ≥ 0.9`, above the
default `τ = 0.75`, whereas two unrelated blocks (nav items vs cards) fall far
below. An exact hash has no tolerance at all.

**Algorithm 002 (sibling-run discovery, after MDR and DEPTA).** For each parent
`p` with element children `c_1..c_k`, and each window size `m ∈ 1..K` and offset
`s ∈ 0..m-1`, form *generalised nodes* `g_j` of `m` adjacent children and compute
`J(M(g_j), M(g_{j+1}))`. A *run* is a maximal sequence of ≥ `r_min = 2` consecutive
generalised nodes with adjacent similarity ≥ `τ` **and** each member within
`τ_c = 0.65` of the run's consensus (element-wise median multiset), which prevents
single-linkage drift (a→b→c each 0.8 but a vs c 0.6). Cost: `M(·)` is computed once
bottom-up with merged maps; each node appears in ≤ `D` ancestor multisets, so the
total size is `O(n·D)`; windows add a factor `≤ K` → **`O(n·D·K)`**, with `D,K`
constants. An optional 16-slot MinHash (Broder 1997) prefilter gives an unbiased
estimate of `J` with variance `J(1-J)/16` and is used only to skip clearly
dissimilar pairs on very wide parents; it never decides.

**Algorithm 003 (ranking and record root).** Candidate runs from all parents are
scored by a log-linear function of: coverage of the main region; log member count;
share of members with ≥ 1 distinct, non-fragment, text-bearing anchor; median text
mass; **pitch regularity** (coefficient of variation of spacing along the stacking
axis, or lattice residual for grids); position; a **chrome penalty** (inside
navigation/header/footer/aside landmarks, or short link text); and an **identity
bonus** that counts an attribute only if its values are pairwise distinct and
non-constant across members (so it *identifies*, instead of merely existing,
fixing defect 2). The tool returns **all runs ranked** with their feature vectors
(fixing defect 8), not a single winner; the engine picks by page family
(results vs facets vs related searches). Record root: for lift levels `ℓ = 0..h`
(h ≤ 12) let `A_ℓ` be the ancestors of the run members `ℓ` levels up. Choose the
smallest `ℓ` where (a) `|A_ℓ| = |run|` (no collapse), (b) subtrees are pairwise
disjoint, and (c) ≥ 80% contain ≥ 1 title candidate **and** ≥ 1 primary anchor.

**Lemma 3 (monotone collapse).** If two members share an ancestor at level `ℓ`
they share one at every `ℓ' > ℓ`. So the set of non-collapsed levels is a prefix
`0..L` and the search terminates in ≤ `h` steps. ∎ This separates the *record
boundary* from the *identity carrier*: the owner measured identity at +10 on Bing
(CB-1) while the card boundary is lower, and identity may sit above, at, or below
the record; today's climb stops at "lowest level with an identity attribute"
(`card_static_resolution.py:152-172`, defect 3).

**Failure modes.** *Returns* `[]` runs with reason `no-repeat` (valid: a
JD page). *Raises*: nothing. *Hangs*: none (all loops bounded by `n·D·K` units and
`h`). *Wrong*: a page whose records are not siblings (flat sequence with
separators, `<dt>/<dd>`, table rows with sub-rows) is handled by `m > 1` windows up
to `K`; records interleaved with unrelated nodes (an ad between every two cards)
yield two interleaved runs unless the offset search merges them (parameter
`allow_gap = 1`); virtualized lists show only the rendered slice (CT-ALG-018).

**Rejected.** *Tree edit distance* (Zhang-Shasha 1989: `O(n1·n2·d1·d2)` per pair;
APTED, Pawlik and Augsten 2016: `O(n³)` worst): unnecessary because records are
sibling-contiguous, so a linear scan of adjacent pairs suffices, and unaffordable
on the worst-case machine. *Exact hash incl. classes*: no tolerance, contradicts
the rule. *Exact hash excl. classes* (the other vocabulary in
`structural_hashing.py`): tolerant of classes but not of one extra node. *DBSCAN*
(Ester et al. 1996): `eps` and `minPts` are scale-dependent, so thresholds rot
with font and viewport. *Full VIPS* (Cai et al. 2003): a rule table built for
2003 layouts. *Kept from VIPS/Gestalt*: the idea of visual separators, in
section 3.

**Examples.** Google web results: result blocks as sibling `div`s with interleaved
widgets; 12-15 candidate groups per page, the selected group at marker fraction
1.00 (R, LR-1). Bing: a list whose items include interleaved ads; identity at +10 (R,
CB-1). Careers boards with rows under department headings, so runs are per section
(O: L09 Jobvite, L19 Ashby, L16 a company site reached from a Greenhouse URL). One board
renders 803 rows at once with facet counts beside the list that are not records (O: L18).
LinkedIn guest job list: cards with title link, company, place and age (O: L43; robots.txt
disallows the path, CT-Q-026).

## 2. Title and link resolution (CT-ALG-004; tool CT-T-009)

*Text rule (fixes defect 4).* `text(v)` = whitespace-normalised concatenation of the
text of **all** visible descendants (excluding `script`, `style`, hidden), plus the
accessible-name sources (`aria-label`, `aria-labelledby`, `title`, `img alt`) per the
Accessible Name Computation. Then `<h3><span>Title</span></h3>` has the title.
Today's adapter keeps only direct text (`math_dom_adapter.py:87-95`); the local
probe reproduces it (`'Engineer 1'` vs `''`).

*Title score.* `s_t = w1[heading] + w2[anchor-related] + w3·z(font-size·weight) + w4·min(len,60)/60 + w5[first in reading order] - w6[metadata-like]`,
where heading = `h1-h6` or `role=heading`, anchor-related = contains, is contained
in, or is adjacent to a primary anchor, and metadata-like = matches date/money/age
patterns. The heading *gate* of today's code is kept as the high-confidence path;
when no heading exists, an anchor name may be the title **only** when the run score
is high and the region is not chrome (keeps tab bars out, the gate's purpose).
*Link score.* `s_l` = relation to title (contains 1.0, contained 1.0, adjacent 0.6)
+ area share + `url_evidence` score (existing, `[WIRED]`). Ties break by document
order, so the result is deterministic. States are the existing enum
(`RESOLVED, MULTI_ROUTE, DEFERRED, NO_DESTINATION`); `MULTI_ROUTE` when two distinct
hrefs are within margin `μ`. A card that **is** an anchor, a custom element, or has
`role=link/button` with `data-href` is a candidate (fixes defect 7).

*Unexplained observation.* One live search selected 8 cards, each with a heading,
and no link scored eligible (LR-1). The evidence available (counts only) cannot
discriminate hypotheses H1 (containment relation missed because the anchor wraps
the heading in a sibling branch), H2 (eligibility floor rejects direct same-host
links), H3 (a wrapper redirect form). Slice 1 captures a fixture and the first
trace, per defect 9, before any threshold is changed. *Pass 3 (S1, cloud):* the
trace on the reachable fixtures confirmed H1 (the detected node sits below the
record: defect 28) and H2 (a same-host posting link scores 0: defect 26), and
found a fourth cause, two links to one destination counted as two routes
(defect 25). H3 was not observed. Section 16 states the S1 rules.

*Failure modes.* Returns `Abstain(no-title)` / `Abstain(no-link)` with candidates
listed; never raises; loops are over the record's nodes (`O(r)`).

*Examples.* Google organic result: heading inside an anchor (K; the cloud client received
the "unusual traffic" page instead, O: L01). Bing: anchor inside heading (R, CB-1 identity
discussion). Jobvite list rows: a table row whose first cell is the title anchor (O: L07).
Anchors with no `href` (38 on one Taleo list, O: L28) and buttons with no target
(O: P15, L53) are candidates only, never resolved links.

## 3. Regions and page family (CT-ALG-005, 006; tool CT-T-007)

*Region tree.* (i) Partition by landmarks (`main`, `nav`, `header`, `footer`,
`aside`, `form`, `section` with a name, and ARIA landmark roles). (ii) Inside
`main`, recursive **XY-cut** (Nagy and Seth 1984; bounding-box form after Ha,
Haralick and Phillips 1995): project child boxes on an axis, cut at the widest empty
gap ≥ `g_min = 1.0 em` (relative to the root font size, so it is scale-free), recurse;
depth ≤ 12. Cost `O(b log b)` per level, worst `O(b²)` if each cut peels one box,
bounded by the depth cap. (iii) Annotate each region with link density and text
density (Kohlschütter, Fankhauser and Nejdl 2010).
*Family.* A log-linear model `score_f = b_f + Σ w_{f,i} φ_i` with features: forms and
visible controls in `main`, best run score, JSON-LD `JobPosting`, URL path tokens,
heading count, text mass, presence of a primary "Apply" control, feed markers
(`role=feed`, `article` runs). `p = softmax(score/T)`, temperature `T` fitted on the
gold set (temperature scaling, Guo et al. 2017). Decision: top family only if
`p ≥ 0.6` and margin ≥ 0.2, else `UNKNOWN`. Weights start hand-set and documented,
later fitted by regularised logistic regression with a fixed seed. Existing page
kinds (`assess_page`, `[LIVE]`) are kept as the *verdict* layer and feed the model as
features; challenge and login dominate (their existing precedence is unchanged).
*Failure:* `UNKNOWN` with the top two families and features; never raises; bounded.
*Rejected:* single-feature rules (a results page also contains a form; a
JD also contains links).
*Examples.* Bing results with a search box (O: L02; today's verdict calls it an
application form, EC-41), Jobvite and Ashby postings with JSON-LD and an apply link
(O: P02, P10), an Ashby application page with two file inputs and no `<form>` (O: F02).

## 4. Forms (CT-ALG-007, 008, 009; tools CT-T-010, 011, 012)

**Segmentation (007).** Controls `C` = HTML form-associated/labelable elements plus
ARIA widgets (`textbox, combobox, listbox, checkbox, radio, switch, slider,
spinbutton`) and `contenteditable`. Form roots: every `<form>` and elements with a
`form=` association; for controls in no form (single-page-app forms), choose the set
of **maximal** nodes `v` with `|C∩T(v)| ≥ 2` and control density `|C∩T(v)| /
|interactive∩T(v)| ≥ 0.4`. *Property:* maximal nodes under the ancestor order form an
antichain, hence a partition of `C`. Cost `O(n)`. Sections: `fieldset/legend`,
`role=group`, intervening headings, XY-cut gaps. Steps: `aria-current=step`, ordered
step lists, `progressbar`; buttons classified next/back/final by type, label lexicon
and step index; unknown is final (CT-INV-004). **Repeating sections** ("add another
education") reuse CT-ALG-002 on the section nodes. *Examples:* Greenhouse posting with one
`<form>` (O: F09), Ashby applications with no `<form>` at all (O: F02-F04), an embedded
Google Form whose questions are `role=listitem` blocks inside one `<form>` with a DIV-based
Submit (O: L57); Workday's multi-step form sits behind an account wall for a guest (O: F05).

**Pairing (008).** Constraint ladder, strongest first: (1) `label[for]`; (2) wrapping
`label` with exactly one labelable control; (3) `aria-labelledby`; (4) `aria-label`;
(5) `fieldset/legend` for groups; (6) `title`/`placeholder` (weak: placeholders vanish
when typed); (7) residual assignment. Residual: unclaimed text blocks `L` and
unlabelled controls `K`, cost
`c(l,k) = α·d_geo/em + β·log(1+d_tree) + γ·orient(l,k) + δ·claimed(l)`, where `orient`
penalises labels on the wrong side (**"start side" is the left in LTR and the right in
RTL**, from computed `direction`) and below-right. Pad to a square matrix with `|L|+|K|`
dummies at cost `c0` (a control prefers "no label" to a bad one) and solve with the
Hungarian (Kuhn 1955, Munkres 1957) or Jonker-Volgenant (1987) method.
*Properties:* optimal total cost (classical); the padding reduces partial assignment
to the square problem, and a padding value of `0.0` (the Bible 9.4 P0 bug) would make
dummies free, hence the explicit `c0`. *Complexity:* `O(m³)` with `m = |L|+|K| ≤ 120`
per section; larger sections are split by the segmentation, so the cap holds.
*Margin:* for control `k`, `c(second best) - c(chosen)`, a heuristic bound, not an exact
conditional (an exact margin needs `m` re-solves; rejected as unaffordable).
*Failure:* no label → `UNLABELED` finding (not a guess); never raises; bounded.
*Rejected:* Hungarian for everything (the 80%+ explicit associations are constraints,
not costs, and should not compete); DBSCAN for label grouping (scale-dependent).
*Examples:* Greenhouse (15 `label[for]`, 8 `aria-labelledby`; O: F09), Ashby (41 `for`
attributes; O: F02), Google Forms (`aria-labelledby` on 10 listitems; O: L57), Lever
(wrapping labels; K).

**Typing (009).** Priority: HTML autofill tokens in `autocomplete` (`given-name`,
`family-name`, `email`, `tel`, `street-address`, `postal-code`, `organization`, …) →
`type` → token (not substring) match of `name/id/label` against locale lexicons →
legend context. Token matching avoids "fax" matching "faxable". Existing scoring
classifier is kept `[WIRED]` and reordered.

## 5. Required, submit prediction, errors (CT-ALG-010, 011, 012; CT-T-013, 026)

**Requiredness fusion (010).** Signals with log-likelihood ratios (initial values,
tuned later): native `required`/`aria-required=true` +6 (as one correlated group,
maximum not sum); **`validity.valueMissing` on an empty control: certain** (no
submit needed, see below); text marker "required"/locale equivalents +3; asterisk +1.5,
raised to +4 when the page carries a legend defining it ("* indicates required");
"(optional)" -5; red-hued marker (computed colour) +2; post-submit error naming the
field +4. **Convention detection:** if > 50% of controls carry "(optional)", unmarked
controls shift toward REQUIRED (the page marks the exception). Output: log-odds ≥ +2
REQUIRED, ≤ -2 OPTIONAL, else UNKNOWN. The independence assumption is false (flagged);
correlated signals are grouped and weights regularised. An UNKNOWN field is *filled if
data exists, else asked*, never skipped as optional.

**Submit prediction (011).** HTML Living Standard: activating a submit button runs
*interactively validate the constraints* unless the form has `novalidate` or the
button has `formnovalidate`; failure aborts submission. Define
`B = ¬novalidate ∧ ¬formnovalidate ∧ button.type=submit ∧ ¬form.checkValidity()`.
**Theorem (native soundness).** If `B` holds and no script prevents default earlier,
the browser's native submission does not occur. **Limit.** Page scripts may run on
`click` before activation and send a request regardless, and apps often use
`type=button` with script-driven submit; the DOM does not reveal listeners (the
protocol call that lists them exists only on Chromium: capability `EVENT_LISTENERS`).
Therefore: output `BLOCKED` only when `B` holds **and** the listener capability shows no
non-native handler on the activation path; `WILL_SUBMIT` when the button is a plain
submit with all constraints satisfied; otherwise `UNKNOWN`, which Applications treats
exactly as `WILL_SUBMIT` (ADR-012: authorisation or nothing). `checkValidity()` is read
only (it fires `invalid` events, shows no UI); `reportValidity()` shows UI and is not
used. **Never press a real final submit to discover requirements.** Pressing a
non-final "Next" to discover is permitted only under CT-Q-015.

**Error mapping (012).** After an attempt: observe again, `DocDiff` (section 8),
candidates = new/changed nodes that are `role=alert`, `aria-live ≠ off`, error-lexicon
text near a control, or controls with `aria-invalid=true`. Map by priority:
`aria-errormessage`/`aria-describedby` id → control; summary anchors `href="#id"` whose
target is a control or its wrapper; nearest common wrapper containing exactly one
control; geometric adjacency; `document.activeElement` after the attempt; `:invalid`
state. Ties → UNKNOWN. **Unmapped errors are always reported** (the engine treats
"errors exist that I cannot map" as failure). *Examples:* inline text under a field
(Greenhouse), top summary with anchors (GOV-style forms), toast + focus jump (K; errors
appear only after a submit, which pass 2 never pressed).

## 6. Visibility, occlusion, honeypots (CT-ALG-013, 014; tool CT-T-005)

`Visible(v) = ∧ over ancestors: display≠none ∧ visibility=visible ∧ opacity>ε ∧
area ≥ a_min ∧ box ∩ clip(overflow ancestors) ≠ ∅ ∧ ¬off-screen beyond a tolerance`.
`aria-hidden` and `inert` are recorded as separate flags: `aria-hidden` removes an
element from assistive technology but not from sight. Occlusion: topmost element at
five sample points (centre + four inset), from `paintOrders` (layout snapshot) or
`elementsFromPoint` (script); occluded fraction `q ∈ {0,0.2,…,1}`. The existing ray
test reads inline style only (`occlusion.py`) `[WIRED]`; computed style requires the
layout snapshot capability.

**Honeypot as a decision, not a flag.** `p(trap) = σ(Σ w_i f_i)` over: invisible (CSS)
`f1` (dominant), no label association `f2`, `tabindex=-1` + `autocomplete=off` `f3`,
trap-token names `f4`, entropy `f5` (small weight: frameworks generate random-looking
names legitimately, e.g. bracketed ATS names). Fill iff `p(trap) < θ`, with
`θ = C_skip / (C_skip + C_trap)`. With `C_trap = 10·C_skip` (a trap trips a bot flag; a
skipped optional field costs a visible, recoverable error) `θ ≈ 0.09`. **Visible and
labelled → fill; invisible → never; visible and unlabelled → UNKNOWN, record, do not
fill.** The cost ratio is a safety parameter and is not tunable (CT-NFR-019).
*Examples:* a hidden `website` input in a newsletter form on a careers page (O: L15;
a candidate, unconfirmed), off-screen "confirm email" (R: the attached conversation lists
them), zero-size input in an invisible container (K). Counter-examples that today's rule
flags wrongly: `address2`, `attestation`, a label to the right in RTL (A: EC-31, EC-32).

## 7. Asynchronous and paged option lists (CT-ALG-015; tool CT-T-015)

States (APG combobox pattern; `aria-expanded`, `aria-controls`, `aria-activedescendant`,
`aria-autocomplete`): `CLOSED → OPEN_LOADING → OPEN_READY | EMPTY`. To select target
`T` (a school): normalise `key(T)` (section 10). Strategies: **S1 typeahead** — type
a prefix of length `ℓ` (3, then grows), settle (section 8), read options, score
`m(T,o)` = max of token-set ratio and normalised edit similarity; accept iff
`m ≥ θ_a` **and** margin to runner-up ≥ `θ_m`; if the list is truncated
(`aria-setsize` > rendered, or a "more" row) lengthen the prefix; **S2 scroll-paging**
— scroll the listbox, wait for growth, stop after `P` rounds with no growth; **S3**
native `select`/`datalist`: read all options. Budget: ≤ `B = 12` settle waits.
*Termination:* the pair `(ℓ, page)` increases lexicographically and is bounded by
`(|T|, P_max)`, so ≤ `B` iterations, each bounded by the settle timeout → total time
≤ `B·W`. *Soundness:* never selects an option with `m < θ_a`. *Completeness:* none
(the target may not be listed): returns `NOT_FOUND(evidence: queries, options seen)`,
or `NOT_FOUND_BUDGET`. Cost for a list of `L` options with server-side filtering is
`O(log L)` queries; without filtering `O(L/p)` pages, capped. A free-text "Other" is
an engine policy, not chosen here.
*Examples:* a 244-entry country-code list inside a phone field and a location
autocomplete combobox (`role=combobox`, `aria-autocomplete`; O: F09, P08); a university
list in an ATS education block and the LinkedIn Easy Apply school field (K; behind account
walls, O: F05, L55).

## 8. Settling, diff, virtualization (CT-ALG-016, 017, 018; CT-T-016)

**Settle (016).** Poll a *volatility-normalised hash* `h_t` of a region (text and
structure; excluding clocks and animations) at intervals `δ_t = min(50·1.5^t, 500) ms`;
settled when `K = 2` consecutive hashes agree, and (with `NETWORK_EVENTS`) no request is
pending, or when `T_max` expires → `Timeout(last hash)`. Terminates by `T_max`. **False
settle**: a debounce longer than `K·δ` (typeahead often 250-400 ms) can look settled;
so typeahead settle requires an observed change *or* a minimum wait `≥ debounce_est`
(default 400 ms). Each poll is one read (a footprint cost, section 7 of 07).

**DocDiff (017).** Key each node by `(parent key, tag, id|name|aria-label|role, ordinal
among equal siblings)`; hash-join old and new; output inserted, removed, text-changed,
attribute-changed, moved. `O(n)`. *Not* tree edit distance (`O(n³)`): DOM changes after
an action are mostly local and keys are stable; unstable keys (regenerated ids) cause
*over*-reporting, which is safe (more re-observation). `diff(a,a)=∅`.

**Virtualization (018, answers R-20).** Detect: (V1) after a scroll step the rendered
row count is ≈ constant while `scrollHeight` grows; (V2) nodes present in both
observations have changed text (recycling) — fraction ≥ 0.3; (V3) `aria-rowcount` or
`aria-setsize` exceeds rendered rows; (V4) rows positioned by increasing
`translateY`/`top` with large spacer elements. Any two signals → `VIRTUALIZED`.
**Smallest staleness guard (value pinning):** read `(title, href)` at observation
time; before any later activation compare the node's current title; mismatch aborts that
activation and re-reads. `O(1)` per activation. Consequence: node handles are never
trusted across a scroll on a virtualized list (a learned identity attribute can point at a
recycled row, a wrong-URL failure with no visible symptom).

## 9. Statistics for tuning (CT-ALG-019; CT-T-019)

*Unit of inference: the site (or template), not the page,* because pages of one site
are correlated. For a candidate change `θ0 → θ1`, replay stored observations (the tools
are pure) and score both against gold labels. For each site `s` record whether `θ1` is
better, worse, or equal. **Test:** one-sided exact sign test on sites where the results
differ (binomial, `p0 = 0.5`), `α = 0.01` per cycle, Holm correction (Holm 1979) across
parameters proposed in the same cycle. **Sample size:** the number of *discordant sites*
needed for power `1-β = 0.8` against a true improvement fraction `p1 = 0.8` is
`n = ((z_{1-α}√(p0q0) + z_{1-β}√(p1q1)) / (p1-p0))²`; with `α=0.05` one-sided this is
`((1.645·0.5 + 0.842·0.4)/0.3)² ≈ 15`, and about 20 with the continuity correction.
So "the last 20 runs" is **necessary only if the 20 are 20 distinct sites that differ
between θ0 and θ1**; twenty runs on five sites support no change. **Guards:** on every
non-targeted family the lower 95% Wilson bound of the accuracy difference must be ≥
-0.01 (non-inferiority); time non-inferiority; a held-out site split (by site hash)
never used to tune. **Application:** the new set is applied at the **next** session
start only; each change moves a parameter ≤ 10% of its range; a cooldown of 5 cycles;
the previous set remains the parent pointer; automatic rollback if the next window
regresses; the user sees the diff, `n`, the statistic and can pin any parameter.
**Peeking** (repeated looks) inflates error; the per-cycle α and the cooldown bound
it. **Goodhart:** gold labels are produced by the labelling tool (blind), independent
of tuning. Safety thresholds (honeypot cost ratio, submit gate, consent) are excluded.
When the evidence is insufficient the answer is **no change**.

## 10. Memory, selection, duty cycling, text, resume, windows, failure classes

**Domain memory (020).** Key = (registrable domain, region-skeleton hash at depth 3,
classes excluded). Entry holds a *hint* (strategy IDs and parameter deltas) and its
*expectations* (record-count range, title-link bijection). Use: only when the general
method abstains or exceeds its budget, or when the profile selects the fast path and
verification is cheap. Verify on every use: the output must satisfy the expectations
and the global invariants; pass → `uses++`; fail → `failures++`, and at 2 the entry is
quarantined (moved to a retired section, not deleted). Absolute expiry (default 30
days); renewal only after 3 verified passes; cap 2,000 entries (about 1 MB), LRU
eviction logged. The memory snapshot hash is part of the run record, so replay uses the
recorded snapshot. Memory is never authoritative (CT-INV-012).

**Selection (021).** Choose the strategy `s` minimising predicted `T_s(n) = a_s + b_s·n`
subject to capability and profile constraints; ties by declared accuracy rank, then by
ID. `(a_s,b_s)` come from the recorded calibration (deterministic).

**Duty cycling (022).** Budgets are in **work units**; `ctx.tick(u)` is called every
≤ 256 units; the meter (infrastructure, not the tool) converts the burst budget to
units using the calibration and sleeps for the rest interval. Tool outputs do not
depend on timing; only `Timeout(partial)` depends on the budget, and it is reproduced
by replaying the same unit budget.

**Text (023; CT-T-003).** *Matching key* `K(s) = casefold(NFKC(strip Cf))` (Unicode
UAX #15); the original is always kept. Dropping format characters is safe **for keys
only**: ZWJ and ZWNJ carry meaning in emoji, Indic and Persian text and are never
removed from values written to a form. *Mojibake:* if
`s.encode('cp1252').decode('utf-8')` succeeds and lowers the count of suspect sequences,
the repair is **suggested** as a finding, never applied silently. *Direction:* UAX #9
rules; logical order is kept; "before" and "start side" use computed `direction`.
*Mixed scripts/confusables:* a token mixing Latin with Cyrillic or Greek is recorded as
obfuscation evidence (UTS #39 skeleton needs a table not in the standard library;
partial by script names). *CJK:* no whitespace tokenisation; character bigrams for
matching. *Grapheme clusters* (UAX #29) are approximated (ZWJ, regional indicators,
variation selectors, combining marks); the limitation is stated. *Unknown language:*
structure only; lexicons add evidence, never gate it; translation is never in the
critical path. Degradation is surfaced as a finding the UI shows.

**Resume (024), windows (025), failure classes (026).** Resume: `epoch++`, enumerate
windows, re-observe, `DocDiff` against the pre-pause `Doc`, classify
`NO_CHANGE | FIELD_EDITS | NAVIGATED | WINDOWS_CHANGED | CHALLENGE_CLEARED | PAGE_GONE`,
re-derive the plan; every planned action carries preconditions (control key, expected
state) and is dropped when they fail; fields the human changed become *human-owned*
and are never overwritten ([08](08_evidence_and_research.md)). Windows: diff the window
set around each action; a new window whose URL carries OAuth/OIDC parameters
(`client_id`, `redirect_uri`, `response_type`, RFC 6749) or a known identity-provider
host is `OAUTH_POPUP`: record, hand to the human, poll for its close with a cap,
`epoch++`, re-observe the parent. Failure classes (the Workbench): from the trace, if
all tools returned confident findings and the engine acted against them →
`WORKFLOW_BUG`; findings correct but the plan lacks a step the page needs →
`WORKFLOW_CHANGE`; a ledger phenomenon present with `tool: none` or a tool abstained on
a page the ledger says it covers → `MISSING_TOOL` / `TOOL_DEFECT`; verdict is
challenge/login/rate-limit → `ACCESS_BLOCKED`; nothing in the ledger matches →
`UNKNOWN_PHENOMENON` (a row is created).

## 11. Budgets (derived; reference machine = 8× slower than the probe machine, an assumption)

| Stage (12,000 nodes) | Probe machine (measured) | Reference budget `[GOAL]` |
| --- | --- | --- |
| Build tree (objects) | 71 ms | n/a; columnar build ≤ 400 ms |
| Group (current exact hash) | 40 ms | n/a |
| Records (`O(n·D·K)`) | not built | ≤ 200 ms |
| Verdict + Regions + Fields | not built | ≤ 250 ms |
| Total analysis | | **≤ 1.0 s** |

Pass 2 adds measurements on real page shapes from the cloud container
(A, [12](12_edge_cases_and_adversity.md) section 5): AA's extraction script takes 6.0 s for 10,000
list rows and 16.1 s for 30,000; today's verdict takes a median of 28 ms, a p95 of 224 ms and a
maximum of 2.8 s over 119 specimens. The measured numbers in the table are synthetic trees on a
4-core Linux machine under Python 3.14, not the owner's pages; the 0.25-0.56 s per pass the owner reported is
most likely dominated by acquisition (script walk forcing layout of every node, JSON
transfer of a 630 KB page), not by these algorithms. That is a hypothesis; slice 0
instruments the stages.

## 12. Worst case, adversarial inputs and tails

Pass 1 gave typical complexity. This section gives, for every algorithm, the
input an adversary or an odd page supplies, the worst-case cost **without** the
cap, the cap that bounds it, and what the algorithm returns when the cap is hit.
The edge cases behind each line are in [12](12_edge_cases_and_adversity.md);
tail budgets per tool (p95, p99, maximum on the worst-case machine) are in its
section 6. Symbols as above, plus `N` = node cap (default 30,000), `B` = byte cap
(8 MB), `S` = sibling cap per parent (2,000), `m` = residual pairing size cap (120).

| ALG | Typical | Adversarial input | Worst case without cap | Cap | On cap |
| --- | --- | --- | --- | --- | --- |
| 001 skeleton multisets | O(n·D) | wide, deep pages | O(n·D), D fixed | `N`, `D` | truncated `Doc` flag |
| 002 sibling runs | O(n·D·K) | parent with 10^4 children; identical children | O(n·D·K); identical children are cheap (J = 1) | `S`; MinHash prefilter | runs over the first `S` children, flag |
| 003 ranking and root | O(runs·h) | runs nested at every level | O(n·h) | `h ≤ 12`, top 50 runs kept | lower-ranked runs dropped, counted |
| 004 title and link | O(r) | record with thousands of anchors | O(r) | 64 anchors per record | `MULTI_ROUTE` |
| 005 region tree | O(b log b) per level | each cut peels one box | O(b²·depth) | depth 12, `b ≤ S` | leaf regions |
| 006 family model | O(features) | none | O(1) | n/a | `UNKNOWN` below margin |
| 007 form segmentation | O(n) | thousands of controls outside forms | O(n) | 500 controls per form | extra controls reported, not segmented |
| 008 pairing | O(m³) residual | 300+ unclaimed text nodes in one section | O((L+K)³), cubic; measured 1.6 s at 302 | `m ≤ 120`, candidates limited to the 8 nearest per control | `UNLABELED` for the rest |
| 009 typing | O(1) | names in unknown languages | O(1) | n/a | `UNKNOWN` type |
| 010 requiredness | O(c) | contradictory markers | O(c) | n/a | `UNKNOWN` |
| 011 submit prediction | O(c) | listeners invisible to the DOM | O(c) | n/a | `UNKNOWN` (= `WILL_SUBMIT`) |
| 012 error mapping | O(Δ) | errors with no association | O(Δ·c) | 200 candidate nodes | unmapped errors reported |
| 013 visibility | O(n log n) | deep clipping chains | O(n·depth) | `D_cap = 64` | `UNKNOWN` visibility |
| 014 honeypot decision | O(1) per control | real fields with trap-like names; RTL | O(1) | n/a | visible and unlabelled → `UNKNOWN`, never filled |
| 015 option lists | O(log L) queries | list that never settles or grows forever | unbounded | 12 settle waits, `P_max` pages | `NOT_FOUND_BUDGET` |
| 016 settle | 2-3 polls | animation, clock, ticker | unbounded polls | `T_max` | `Timeout(last hash)` |
| 017 DocDiff | O(n) | regenerated keys | O(n), over-reporting | `N` | complete re-observation |
| 018 virtualisation | O(rows) | recycled rows | O(rows) | n/a | activation aborted on pin mismatch |
| 019 tuning | offline | adversarial traces | offline | cooldown, ≤ 10% move | no change |
| 020 memory | O(1) | poisoned hint | O(1) | 2,000 entries | quarantine |
| 021 selection | O(strategies) | n/a | O(1) | n/a | conservative strategy |
| 022 duty cycling | O(1) per tick | thermal throttling | n/a | units, not seconds | `Timeout(partial)` reproducible on replay |
| 023 text | O(chars) | huge text, confusables, mojibake | O(chars) | `B` | flags, never rewrites values |
| 024 resume | O(n) | page replaced during pause | O(n) | `N` | `PAGE_GONE` |
| 025 windows | O(windows) | window storm (pop-ups opening pop-ups) | unbounded windows | 4 new windows per action | close AA-opened extras, `WINDOWS_CHANGED` |
| 026 failure classes | O(trace) | n/a | O(trace) | trace caps | `UNKNOWN_PHENOMENON` |
| 027 filter effect | O(r) | page re-ranks on every load | O(r) | `S` records, 2 confirmations | `UNKNOWN`; parameter not learned |
| 028 view equivalence | O(fields + tokens) | huge descriptions | O(B) | byte cap | `compatible` with the cut field flagged |
| 029 view selection | O(V·F) | many views | O(V·F) | views per record 16 | conservative choice: the page view |

**Lemma 4 (every tool terminates).** Each loop above iterates over a finite,
capped collection (`N`, `S`, `m`, `h`, a page or wait count) or polls with a
strictly increasing clock bounded by `T_max`. A tool's total work is therefore
at most the product of its caps, a constant per profile, and every cap breach
yields a typed result. *Proof sketch:* by inspection of the table; the only
unbounded quantities on the open web (node count, text nodes per section,
settle time, list length, window count) each sit behind a cap. ∎ The
guarantee G2 of [01](01_charter.md) depends on these caps being enforced at the
tool boundary, not inside the engines.

**What today's code lacks** (A, offline probes, [12](12_edge_cases_and_adversity.md) section 5):
there is no node, byte or time cap on the extraction script (30,000 rows: 16 s,
11 MB here); label pairing runs a square Hungarian over every visible text node
in the container (cubic, no cap); `iter_nodes` recurses. So G2 does not hold at
`1bf7935`. CT-NFR-010 moves from `[~]` to `[ ]` in pass 2 on this evidence.

**Typical against tail.** A typical page (2,000 to 5,000 nodes, one form of
10 to 40 controls) costs tens of milliseconds per tool here. The tails come
from three page shapes seen in the specimens: very long lists (C14: 38,000 nodes
after scrolling), text-heavy containers around forms (L16), and pages served as
one large script payload. Budgets are set on those shapes, not on the median.

## 13. Filter effect verification and parameter learning (CT-ALG-027; tool CT-T-027)

**Input.** Two observations of the same surface, `O_b` before and `O_a` after
one `ActionRequest` on a control bound to piece `p` with intended option `v`;
their record sets `R_b`, `R_a` (record identities from CT-T-008/009: the
canonical URL of each record's link, else its identity attribute value),
their total-count texts `c_b`, `c_a` (parsed integers or none), and URLs
`u_b`, `u_a`.

**Statement.** Let `J = |R_a ∩ R_b| / |R_a ∪ R_b|` (Jaccard, 1 when both are
empty). Let `Δq` be the query-string difference between `u_b` and `u_a`
(keys added, removed or with changed values; the fragment is ignored).
Decide, in order:

1. `|R_a| = 0` and the verdict on `O_a` is an empty-results state →
   `APPLIED` with `empty=true` (a filter can legitimately empty a list).
2. `J = 1` and `c_a = c_b` and `Δq = ∅` → `NO_EFFECT`.
3. `J = 1` and (`Δq ≠ ∅` or `c_a ≠ c_b`) → `NO_EFFECT` with
   `url_changed`/`count_changed` evidence (the CT-PH-226 case: the URL moved,
   the results did not; the `VerifiedPageAdvancer` lesson).
4. `J < 1` → `APPLIED`; additionally, when every record of `R_a` that carries
   the filtered field (date, remote flag, pay) satisfies `v`, the check is
   `APPLIED+consistent`; when some contradict `v`, `CONTRADICTED` with the
   count of contradicting records.
5. If `c_a` is present and `|R_a| > c_a` on a page that shows all results,
   or the facet count shown for `v` differs from `c_a` by more than the page
   size, add `count_mismatch` (CT-PH-228).

`RESET` is decided on the next page: after `advance_page`, if the control's
`current` value (CT-DS-014) is back to its default, the outcome of the
earlier `APPLIED` is revised to `RESET` for pages after the first.

**Parameter learning (step 4).** On `APPLIED` with `|Δq| = 1` (one key, or
one value) the pair `(key, value)` is a candidate for `(host, p, v)`. With
`|Δq| > 1`, keys present in both before and after with tracking-shaped
names (the tokens of `url_evidence`) are dropped first; if one key remains it
is the candidate, else no candidate. A candidate is confirmed by navigating
to `u_b` with only that change applied and observing `J ≥ 0.9` against
`R_a` (pagination and ads perturb a little). Two confirmations on different
queries promote it to the catalog with provenance `learned`.

**Proof sketch (soundness of `NO_EFFECT`).** If the filter had taken effect
on the first page, the record set would change unless every record on the
page already satisfied `v`. That case is indistinguishable from no effect on
one page; the check therefore reports `NO_EFFECT` only as a page-level fact,
and the channel is benched only after the same outcome on two queries
(ADR-021's verifier rule). False `APPLIED` requires `R_a ≠ R_b` without the
filter acting, which happens when the page re-ranks on every load; the
learning step's direct-URL confirmation catches it with probability equal to
the chance two independent reloads agree, measured per host in S0.

**Termination and cost.** No loops beyond set operations over the records of
two pages (`r ≤ 2,000`, the sibling cap): `O(r)` with hashing. One extra
navigation per confirmation, two per learned parameter, once per host and
piece. Budget on the worst-case machine: the observation dominates (S1
measured 32 to 281 ms per pass on live boards in the cloud; times 8 for the
reference machine), the decision itself under 1 ms.

**Failure modes.** Returns `UNKNOWN` when either observation is truncated,
blocked or a challenge (the verdict decides), or when record identity is
unavailable (no links, no identity attribute). Never raises; never retries
on its own (the engine decides, under ADR-021's bench rule).

## 14. View equivalence (CT-ALG-028; tool CT-T-028)

**Input.** Two views `A`, `B` claimed to show the same record, each reduced
to fields `f ∈ {title, company, location, pay, date_posted, valid_through,
apply_target, description}` with values from CT-T-009/017 (page views) or
the parsed payload (feed, API, sitemap).

**Statement.** Per field, compare normalised values (text key `K(s)` of
s10; locations by the normalised place tuple; pay as intervals; dates as
calendar days in the view's stated zone; apply targets by canonical URL;
descriptions by token-set Jaccard). Field `f` *agrees* if equal (`J ≥ 0.8`
for descriptions, interval overlap for pay, `|Δdays| ≤ 1` for dates). The
views are **equivalent** when the identity fields (title, and one of company
or apply target) agree and no present field disagrees; **compatible** when
identity agrees and some fields differ (reported, never averaged); **distinct**
otherwise. The record's value for a field comes from the view with the
higher field confidence, and the disagreement stays in the record.

**Sampling.** A learned `ViewTemplate` is re-verified on a random sample
(seeded) of `max(3, ⌈0.05·n⌉)` records per run; a single `distinct` result
quarantines the template (domain-memory rule, s10).

**Termination and cost.** `O(|f| + description tokens)` per pair, bounded by
the byte cap; feeds and APIs are parsed once. No network inside the
algorithm.

## 15. View selection (CT-ALG-029)

**Statement.** For a record with needed fields `F` and verified views `V`
(ALG-028 `equivalent` or `compatible` on `F`), choose
`argmin_{v ∈ V, access(v) = public, F ⊆ fields(v)} (footprint_class(v), requests(v), bytes(v))`
lexicographically; ties by view kind order (`api`, `feed`, `jsonld`,
`page_guest`, `print`, `amp`, `mobile`, `embedded`, `own_url`), then by
locator. If no view carries all of `F`, choose the cover with the fewest
views by the same order (greedy set cover; `|F| ≤ 8` makes the greedy bound
irrelevant in practice). Deterministic. `O(|V|·|F|)`.

**Why footprint first.** A plain GET of a feed or API is one request with no
script execution and no input events ([07](07_footprint_and_defences.md) s3);
the page view costs a browser load. Accuracy is not traded: only verified
views are candidates.

## 16. The S1 record reading, as built (CT-ALG-003 and 004, smallest form)

Slice S1 implements the record-root rule and the title rule in the smallest
form that slice S2's records tool replaces. Precisely:

1. **Levels.** The climb keeps levels `ℓ = 0..h` while the lifted nodes stay
   one per card (`h ≤ 12`, Lemma 3).
2. **Heading tier.** Choose the smallest `ℓ` at which at least 80% of the
   nodes are pairwise disjoint and hold a heading with text (accessible name,
   else full-subtree text) **and** a primary link related to it: the link
   contains the heading or sits inside it, or its name or URL carries at
   least half of the title's tokens. A block holding a title and only an
   unrelated link (a company link) does not qualify.
3. **Link tier.** Only if no level qualifies in step 2: the smallest `ℓ` at
   which 80% hold a primary link with a name. Records there take the link's
   name as title when they are outside chrome landmarks and the names and
   destinations are each at least 80% distinct across the group (a column
   of "Apply" links fails).
4. **Fallback.** No level qualifies: read the cards at the identity level
   (today's behaviour), so anchorless cards keep their identity for click
   activation.
5. **Link choice.** Candidates are scored by `url_evidence` plus a
   title-relation term of 0.5; candidates with one canonical destination are
   merged before the resolution state is decided.

*Termination:* at most two passes over at most 13 levels; each level's test
walks disjoint subtrees once, so the cost is `O(13·n)` worst case, measured
at under 35 ms on 1,147-node live boards (cloud). *Proven by:* the pins of
`tests/domain/test_s1_record_reading.py` and the four fixture pins;
*replaced by:* S2's ranked runs, run score and chrome penalty.
