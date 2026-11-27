"""S5 pins: DocDiff, settle, conditional fields, errors, windows, resume,
and the LinkedIn patterns (synthetic fixtures; LinkedIn's real markup is
unverified, owner to confirm live)."""

from __future__ import annotations

from pagecomp.doc import from_html
from pagecomp.results import Stale, Timeout
from pagecomp.transitions import (
    AD_UNKNOWN,
    CHALLENGE_CLEARED,
    DIALOG,
    EXTERNAL_APPLY,
    FIELD_EDITS,
    NAVIGATED,
    NO_CHANGE,
    OAUTH_POPUP,
    OVER_CAP,
    PAGE_GONE,
    SETTLED,
    SETTLING,
    WINDOWS_CHANGED,
    ConditionalLoop,
    PauseContext,
    PlannedStep,
    Question,
    Settler,
    WindowEvent,
    WindowSet,
    classify_window,
    diff,
    map_errors,
    node_keys,
    resume,
)


def _inputs(doc):
    return [i for i in doc.elements() if doc.tag_name(i) in ("input", "select", "textarea")]


# -- DocDiff -----------------------------------------------------------------

def test_diff_of_identical_is_empty():
    d = from_html("<div><input name=a><p>x</p></div>")
    assert diff(d, d).empty


def test_diff_uses_keys_not_indexes():
    a = from_html("<form><input name=a><input name=b></form>")
    b = from_html("<form><p>banner</p><input name=a><input name=b></form>")  # indexes shift
    d = diff(a, b)
    assert [b.tag_name(i) for i in d.added] == ["p", ""] or {b.tag_name(i) for i in d.added} <= {"p", ""}
    assert not d.removed


def test_diff_reports_removed_and_changed():
    a = from_html("<div><input name=a value=1><span id=s>old</span></div>")
    b = from_html("<div><input name=a value=2></div>")
    d = diff(a, b)
    assert any(a.tag_name(i) == "span" for i in d.removed)
    assert any(b.tag_name(j) == "input" for _, j in d.changed)


def test_identical_siblings_get_distinct_keys():
    d = from_html("<ul>" + "<li>x</li>" * 50 + "</ul>")
    keys = node_keys(d)
    lis = [keys[i] for i in d.elements("li")]
    assert len(set(lis)) == 50


# -- Settle ------------------------------------------------------------------

def test_settle_after_quiet_reads():
    s = Settler(quiet=2, t_max=10)
    assert s.observe("h1", 0.0) == SETTLING
    assert s.observe("h2", 0.1) == SETTLING
    assert s.observe("h2", 0.2) == SETTLING
    assert s.observe("h2", 0.3) == SETTLED


def test_settle_times_out_on_a_ticking_page():
    s = Settler(quiet=2, t_max=10)
    r = None
    for t in range(200):
        r = s.observe(f"tick{t}", t * 0.5)
        if r != SETTLING:
            break
    assert isinstance(r, Timeout) and r.partial.startswith("tick")


def test_settle_read_cap_bounds_a_frozen_clock():
    s = Settler(quiet=2, t_max=10, max_reads=5)
    out = [s.observe(i, 0.0) for i in range(5)]
    assert isinstance(out[-1], Timeout)


def test_settle_interval_is_bounded():
    assert Settler.interval(0) == 0.05 and Settler.interval(100) == 0.5


# -- Conditional fields ------------------------------------------------------

Q = lambda n, k="text": Question(("f", n, "", n), k)  # noqa: E731


def test_yes_reveals_follow_up_after_one_round():
    loop = ConditionalLoop([Q("auth", "radio"), Q("name")])
    assert loop.needs_reobserve(loop.questions[0])
    r = loop.after_answer(Q("auth").key, "Yes", [Q("auth", "radio"), Q("visa"), Q("name")])
    assert r.revealed == (Q("visa").key,) and r.agenda[0] == Q("visa").key
    assert r.status == "continue" and loop.edges == [(Q("auth").key, (Q("visa").key,))]


def test_withdrawn_questions_drop_their_values():
    loop = ConditionalLoop([Q("auth", "radio"), Q("visa")])
    loop.answers[Q("visa").key] = "H1B"
    r = loop.after_answer(Q("auth").key, "No", [Q("auth", "radio")])
    assert r.withdrawn == (Q("visa").key,) and Q("visa").key not in loop.answers


def test_repeated_state_is_a_cycle():
    loop = ConditionalLoop([Q("a", "radio"), Q("b", "radio")])
    loop.after_answer(Q("a").key, "1", [Q("a", "radio"), Q("b", "radio")])
    r = loop.after_answer(Q("a").key, "1", [Q("a", "radio"), Q("b", "radio")])
    assert r.status == "cycle"


def test_round_cap():
    loop = ConditionalLoop([Q("a", "radio")])
    status = ""
    for n in range(20):
        status = loop.after_answer(Q("a").key, str(n), [Q("a", "radio"), Q(f"x{n}")]).status
        if status in ("cap", "cycle"):
            break
    assert status == "cap" and loop.rounds <= 11 + 1


def test_text_inputs_do_not_trigger_reobserve():
    assert not ConditionalLoop([Q("n")]).needs_reobserve(Q("n"))
    assert ConditionalLoop([Q("c", "combobox")]).needs_reobserve(Q("c", "combobox"))


# -- Errors ------------------------------------------------------------------

BEFORE = ("<form><div class=f><label>Email</label><input name=email></div>"
          "<div class=f><label>Phone</label><input name=phone></div>"
          "<div class=f><label>City</label><input name=city></div><button>Next</button></form>")


def test_errors_mapped_by_ladder_and_generalised_by_skeleton():
    after_html = ("<form><div class=f><label>Email</label>"
                  "<input name=email aria-invalid=true aria-describedby=e1>"
                  "<div id=e1 class=err><span>This field is required</span></div></div>"
                  "<div class=f><label>Phone</label><input name=phone>"
                  "<div class=err><span>Formato no válido</span></div></div>"   # no lexicon word
                  "<div class=f><label>City</label><input name=city></div><button>Next</button></form>")
    a, b = from_html(BEFORE), from_html(after_html)
    errs = map_errors(b, diff(a, b), _inputs(b))
    by = {b.attr(e.control, "name"): e for e in errs}
    assert by["email"].rung == "aria-describedby" and not by["email"].learned
    assert by["phone"].learned and by["phone"].rung == "container"
    assert "city" not in by


def test_unmapped_errors_are_reported_not_dropped():
    after_html = "<div role=alert>Something went wrong</div>" + BEFORE
    a, b = from_html(BEFORE), from_html(after_html)
    errs = map_errors(b, diff(a, b), _inputs(b))
    assert len(errs) == 1 and errs[0].control == -1 and errs[0].rung == "unmapped"


# -- Windows -----------------------------------------------------------------

def test_window_kinds():
    o = WindowEvent("w1", "https://accounts.google.com/o/oauth2/auth?client_id=1&redirect_uri=x")
    assert classify_window(o) == OAUTH_POPUP
    assert classify_window(WindowEvent("w", "https://idp.example/a?client_id=x&response_type=code")) \
        == OAUTH_POPUP
    assert classify_window(WindowEvent("w", "https://boards.greenhouse.io/x/jobs/1"),
                           apply_hosts=("greenhouse.io",)) == EXTERNAL_APPLY
    assert classify_window(WindowEvent("w", "https://acme.example/careers/1"),
                           expected_apply=True) == EXTERNAL_APPLY
    assert classify_window(WindowEvent("w", "https://ad.doubleclick.net/x"), expected_apply=True) \
        == AD_UNKNOWN
    assert classify_window(WindowEvent("w", "about:blank")) == AD_UNKNOWN
    assert classify_window(WindowEvent("d", "", kind="dialog")) == DIALOG


def test_window_cap_per_action():
    ws = WindowSet(known={"main"})
    handles = {"main": "https://a/"} | {f"p{k}": f"https://spam{k}.example/" for k in range(7)}
    out = ws.after_action(handles)
    assert sum(1 for d in out if d.kind == OVER_CAP) == 3
    assert all(d.action == "close" for d in out)
    assert ws.after_action(handles) == ()  # nothing new the second time


def test_linkedin_apply_opens_external_tab():
    """Pattern: 'Apply' on a guest posting opens the company ATS in a new tab.
    (LinkedIn markup unverified, owner to confirm live.)"""
    ws = WindowSet(known={"main"})
    out = ws.after_action({"main": "https://www.linkedin.com/jobs/view/1",
                           "t2": "https://jobs.lever.co/acme/123"},
                          opener_action="apply", expected_apply=True)
    assert [(d.kind, d.action) for d in out] == [(EXTERNAL_APPLY, "follow")]


def test_linkedin_sign_in_popup_goes_to_human():
    ws = WindowSet(known={"main"})
    out = ws.after_action({"main": "x", "p": "https://www.linkedin.com/oauth/v2/authorization?"
                                             "client_id=a&redirect_uri=b&response_type=code"})
    assert out[0].kind == OAUTH_POPUP and out[0].action == "hand-to-human"


# -- LinkedIn page patterns (synthetic; unverified, owner to confirm live) -----

def test_linkedin_easy_apply_steps_change_dom_without_load():
    step1 = from_html("<div role=dialog aria-label='Apply'><h3>Contact</h3><input name=phone>"
                      "<button aria-label='Continue to next step'>Next</button></div>")
    step2 = from_html("<div role=dialog aria-label='Apply'><h3>Resume</h3><input type=file name=cv>"
                      "<button aria-label='Review your application'>Review</button></div>")
    d = diff(step1, step2)
    assert not d.empty
    dialogs = [i for i in step2.elements("div") if step2.attr(i, "role") == "dialog"]
    assert dialogs and all(i not in d.added for i in dialogs)   # same modal, new content


def test_linkedin_sign_in_modal_over_guest_page_is_overlay():
    from pagecomp.observation import observe_html
    from pagecomp import analyze

    html = ("<main><h1>Engineer</h1><p>" + "About the role. " * 40 + "</p></main>"
            "<div role=dialog aria-modal=true><h2>Sign in to see more</h2>"
            "<input name=session_key type=email><input name=session_password type=password>"
            "<button>Sign in</button><button aria-label=Dismiss>×</button></div>")
    obs = observe_html(html, url="https://www.linkedin.com/jobs/view/1")
    v = analyze(obs, "verdict")["verdict"]
    assert v.ok
    assert not v.value.login_wall and "dialog" in v.value.overlays   # overlay, not a wall
    assert len(obs.doc.text_content(next(obs.doc.elements("main")), 4000)[0]) > 300


def test_linkedin_pushstate_increments_epoch_and_makes_findings_stale():
    from pagecomp.access import ReadProbe, read_flags

    flags = read_flags(ReadProbe("https://www.linkedin.com/jobs/search/?k=a", "1", 0),
                       ReadProbe("https://www.linkedin.com/jobs/view/2/", "1", 0))
    assert "spa-navigated" in flags and "stale" in flags
    ctx = PauseContext("h", 3, "https://www.linkedin.com/jobs/search/?k=a", ("f",), (), 0.9)
    r = resume(ctx, new_epoch=3, old_doc=None, new_doc=from_html("<p>x</p>"),
               new_url="https://www.linkedin.com/jobs/view/2/", windows_now=frozenset(),
               challenge_now=False)
    assert r.epoch == 4 and r.classification == NAVIGATED and isinstance(r.stale[0], Stale)


def test_linkedin_virtualized_list_only_visible_slice_diffs_as_recycling():
    a = from_html("<ul aria-rowcount=500>" + "".join(f"<li data-id={k}>Job {k}</li>"
                                                      for k in range(10)) + "</ul>")
    b = from_html("<ul aria-rowcount=500>" + "".join(f"<li data-id={k}>Job {k}</li>"
                                                      for k in range(10, 20)) + "</ul>")
    d = diff(a, b)
    # same keys (position among equal siblings), different payloads: recycled rows
    assert len(d.changed) >= 10 and not d.added
    ul = next(b.elements("ul"))
    assert int(b.attr(ul, "aria-rowcount")) > sum(1 for _ in b.elements("li"))


def test_linkedin_toast_is_added_then_removed():
    a = from_html("<main><p>x</p></main>")
    b = from_html("<main><p>x</p></main><div role=status aria-live=polite>Saved</div>")
    assert diff(a, b).added and diff(b, a).removed


def test_linkedin_ad_and_messaging_iframes_recorded_not_read():
    from pagecomp.doc import from_cdp

    def el(tag, attrs, **kw):
        return {"nodeType": 1, "localName": tag, "attributes": [x for kv in attrs for x in kv],
                "children": [], **kw}
    root = {"nodeType": 9, "documentURL": "https://www.linkedin.com/feed/", "children": [
        el("html", [], children=[
            el("iframe", [("src", "https://ads.example/x")], frameId="ad", frameState="frame-cap"),
            el("iframe", [("src", "https://www.linkedin.com/messaging/")], frameId="m")])]}
    root["children"][0]["children"] = [
        el("iframe", [("src", "https://ads.example/x")], frameId="ad", frameState="frame-cap"),
        el("iframe", [("src", "https://www.linkedin.com/messaging/")], frameId="m")]
    doc = from_cdp(root)
    states = {f.url: f.state for f in doc.frames}
    assert states["https://ads.example/x"] == "frame-cap"
    assert states["https://www.linkedin.com/messaging/"] == "not-loaded"


def test_modal_inside_shadow_container_is_read():
    html = ("<app-shell><template shadowrootmode=open><div role=dialog><input name=phone>"
            "</div></template></app-shell>")
    d = from_html(html)
    assert any(d.attr(i, "name") == "phone" for i in d.elements("input"))


# -- Pause and resume (HITL table, 12 s2 and 06 s10) -------------------------

PAGE = "<form><input name=a value=1><input name=b value=2></form>"


def _ctx(doc, **kw):
    keys = node_keys(doc)
    a = next(i for i in doc.elements("input") if doc.attr(i, "name") == "a")
    from pagecomp.transitions import control_values
    base = dict(observation_id="h", epoch=5, url="https://x/f", findings=("f1", "f2"),
                intended=(PlannedStep(keys[a], "set_text", "1"),), confidence=0.8,
                windows=frozenset({"main"}), values=control_values(doc))
    base.update(kw)
    return PauseContext(**base)


def _resume(ctx, new_doc, url="https://x/f", windows=frozenset({"main"}), challenge=False,
            old=None):
    return resume(ctx, new_epoch=ctx.epoch, old_doc=old, new_doc=new_doc, new_url=url,
                  windows_now=windows, challenge_now=challenge)


def test_resume_no_change_keeps_plan_but_findings_are_stale():
    d = from_html(PAGE)
    r = _resume(_ctx(d), d, old=d)
    assert r.classification == NO_CHANGE and r.kept and r.epoch == 6
    assert all(isinstance(s, Stale) for s in r.stale) and len(r.stale) == 2


def test_resume_human_edit_is_human_owned_and_step_dropped():
    d = from_html(PAGE)
    edited = from_html("<form><input name=a value=9><input name=b value=2></form>")
    r = _resume(_ctx(d), edited, old=d)
    assert r.classification == FIELD_EDITS and r.dropped and r.human_owned


def test_resume_navigated_drops_everything():
    d = from_html(PAGE)
    r = _resume(_ctx(d), d, url="https://x/elsewhere")
    assert r.classification == NAVIGATED and not r.kept


def test_resume_windows_changed():
    d = from_html(PAGE)
    assert _resume(_ctx(d), d, windows=frozenset({"main", "pop"})).classification == WINDOWS_CHANGED


def test_resume_challenge_cleared():
    d = from_html(PAGE)
    assert _resume(_ctx(d, challenge=True), d).classification == CHALLENGE_CLEARED


def test_resume_page_gone():
    d = from_html(PAGE)
    r = _resume(_ctx(d), None)
    assert r.classification == PAGE_GONE and r.dropped and not r.kept


def test_resume_control_missing_drops_its_step():
    d = from_html(PAGE)
    r = _resume(_ctx(d), from_html("<form><input name=b value=2></form>"), old=d)
    assert r.dropped and not r.kept
