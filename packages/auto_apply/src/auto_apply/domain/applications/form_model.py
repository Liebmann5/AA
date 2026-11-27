"""The step engine's model of one application-form step. Pure data.

A *step* is what one page of an application shows at one moment: the
questions on it, the buttons that move it on, and how each control can be
found again in the live page. The perception adapter builds it from a
pagecomp reading; the engine reads it, decides, acts through the shared
interaction tool, and reads the page again. Nothing here touches a browser.

Vocabulary (one taxonomy, pagecomp's): ``field_type`` is the canonical
semantic type pagecomp's form reader assigns (``first_name``, ``email``,
``work_authorization`` ...); ``kind`` is the widget shape the actuator must
operate (``text``, ``select``, ``combobox``, ``radio`` ...). Requiredness,
trap decisions and sensitivity are pagecomp's verdicts, carried unchanged so
a research record can be traced back to the reading that produced it.

Identity. A :class:`ControlRef` names a control by its element path from the
document (the index of each element among its parent's element children,
with ``s`` hops into open shadow roots) plus its tag, type, name and id.
The adapter resolves the path and checks the identity before any action, so
a page that re-rendered between the reading and the action yields "not
found", never an action on the wrong element.
"""

from __future__ import annotations

from dataclasses import dataclass

from auto_apply.domain.applications.form_language import says

#: Requiredness verdicts (pagecomp formread). UNKNOWN is never treated as
#: optional by the reader; the engine leaves an UNKNOWN field it cannot answer
#: and lets the page's own validation say whether it was needed.
REQUIRED = "REQUIRED"
OPTIONAL = "OPTIONAL"
UNKNOWN = "UNKNOWN"


def says_submit(text: str) -> bool:
    """Does a control's text say it sends something, in any language?

    One rule: the engine's choice of controls and the actuator's refusal
    both use it (``form_lexicon`` class ``submit``, matched everywhere).
    """
    return says(text, "submit")


#: Fill decisions (pagecomp formread). Only FILL questions are ever acted on.
FILL = "FILL"
TRAP = "TRAP"
HIDDEN = "HIDDEN"
UNLABELLED = "UNKNOWN"
SKIP = "SKIP"


class QuestionKind:
    """The widget shapes the actuator knows how to operate."""

    TEXT = "text"
    TEXTAREA = "textarea"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    COMBOBOX = "combobox"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    CHECKBOX_GROUP = "checkbox_group"
    FILE = "file"
    DATE = "date"
    PASSWORD = "password"
    OTHER = "other"

    CHOICE = frozenset({SELECT, MULTI_SELECT, COMBOBOX, RADIO, CHECKBOX, CHECKBOX_GROUP})
    #: Answering these can reveal or withdraw other questions.
    REVEALING = frozenset({SELECT, MULTI_SELECT, COMBOBOX, RADIO, CHECKBOX, CHECKBOX_GROUP})


@dataclass(frozen=True)
class ControlRef:
    """How to find one live control again.

    Attributes:
        path: Element path from the document: ``("c", k)`` is the k-th element
            child, ``("s", 0)`` steps into an open shadow root.
        tag: Lower-case tag name, checked before acting.
        type: Input type, ``select``, ``textarea``, ``role:<r>`` or
            ``contenteditable`` (pagecomp's control type).
        name: The ``name`` attribute, checked when present.
        id: The ``id`` attribute, checked when present and used as the
            fallback locator inside the same scope.
        in_frame: The control lives in a frame document. Frames are not
            acted in place; the workflow opens the frame's address instead.
        in_shadow: The path crosses at least one shadow root.
    """

    path: tuple[tuple[str, int], ...]
    tag: str
    type: str = ""
    name: str = ""
    id: str = ""
    in_frame: bool = False
    in_shadow: bool = False

    def as_spec(self) -> dict[str, object]:
        """The JSON-ready form the adapter's resolver script reads."""
        return {
            "path": [[rel, k] for rel, k in self.path],
            "tag": self.tag,
            "name": self.name,
            "id": self.id,
        }

    def describe(self) -> str:
        """A short, PII-free description for logs."""
        bits = [self.tag]
        if self.type and self.type != self.tag:
            bits.append(f"type={self.type}")
        if self.name:
            bits.append(f"name={self.name[:40]}")
        if self.id:
            bits.append(f"id={self.id[:40]}")
        return " ".join(bits)


@dataclass(frozen=True)
class FormOption:
    """One choice of a choice question.

    Attributes:
        label: What a person reads for this option.
        value: The option's ``value`` attribute ("" when it has none).
        control: The input that represents the option (radio/checkbox groups).
        click_target: What a person clicks to choose it — the option's label
            when the input itself is visually replaced. None means the
            control itself.
    """

    label: str
    value: str = ""
    control: ControlRef | None = None
    click_target: ControlRef | None = None


@dataclass(frozen=True)
class FormQuestion:
    """One question: a single control, or a radio/checkbox group."""

    key: str
    label: str
    kind: str
    field_type: str
    controls: tuple[ControlRef, ...]
    type_source: str = ""
    required: str = UNKNOWN
    required_evidence: tuple[str, ...] = ()
    sensitive: bool = False
    decision: str = FILL
    options: tuple[FormOption, ...] = ()
    description: str = ""
    input_type: str = ""
    max_length: int | None = None
    autocomplete: str = ""
    #: Where the reader found the label (``label-for``, ``aria-labelledby``,
    #: ``placeholder``, ``none`` ...): research evidence of how a form names
    #: its questions, and of the ones it does not name at all.
    label_source: str = ""
    #: How many options a multi-choice question allows ("pick the best 2",
    #: "select up to 3", "wählen Sie mindestens eine"): 0 means no bound
    #: is known. Read by the language layer (``selection_limits``); AA
    #: never ticks more, or fewer, than the question allows.
    choose_min: int = 0
    choose_max: int = 0
    #: How the limit was known, e.g. ``words(en):up to 3`` (evidence).
    choose_evidence: str = ""

    @property
    def primary(self) -> ControlRef:
        """The control an action starts from."""
        return self.controls[0]

    @property
    def is_choice(self) -> bool:
        return self.kind in QuestionKind.CHOICE

    @property
    def is_required(self) -> bool:
        return self.required == REQUIRED


@dataclass(frozen=True)
class FormLink:
    """A link inside the application form's area, with the text around it.

    The perception reports links and their nearby text; the language layer
    decides what they are (``external_steps``): an assessment the person is
    sent to, or another form the page says must be completed first.
    """

    href: str
    text: str
    context: str = ""


@dataclass(frozen=True)
class FormButton:
    """A button of the application form, as pagecomp classified it.

    ``role`` is ``next`` / ``back`` / ``review`` / ``submit`` / ``other``;
    ``final`` is the conservative verdict that clicking it may submit (an
    unclassified button may submit — CT-INV-004). ``role_source`` says who
    decided the role: ``pagecomp`` (the reader) or ``lexicon(<lang>)`` (AA's
    multilingual words, ``form_localization.localize_step``).
    """

    role: str
    text: str
    control: ControlRef
    final: bool
    button_type: str = ""
    role_source: str = ""

    @property
    def may_submit(self) -> bool:
        """Could clicking this send the application? Fail closed.

        True when it was not shown to be a step control (``final``), when the
        reader called it a submit control (``role == "submit"`` — a
        contradictory or incomplete reading never makes it safe), or when its
        text says it sends something in any language ("Submit and continue",
        "Envoyer", "送信"), whatever its role. An HTML ``type=submit`` alone is
        not evidence either way: a ``<button>`` with no type attribute is a
        submit button by the HTML default, which is how most multi-step forms
        mark their Next — the engine weighs that separately.
        """
        return self.final or self.role == "submit" or says_submit(self.text)


@dataclass(frozen=True)
class FrameCandidate:
    """A frame that may hold the application form."""

    url: str
    same_origin: bool
    state: str
    holds_form: bool = False


@dataclass(frozen=True)
class FormStep:
    """One reading of the application form as it stands right now."""

    url: str
    title: str
    purpose: str
    questions: tuple[FormQuestion, ...]
    buttons: tuple[FormButton, ...]
    fingerprint: str
    step_label: str = ""
    frame_candidates: tuple[FrameCandidate, ...] = ()
    form_in_frame: bool = False
    complete_read: bool = True
    read_notes: tuple[str, ...] = ()
    #: The ``lang`` the page declares for the form ("" when it declares none).
    language: str = ""
    #: The candidate languages AA matched words in (``form_language.resolve``).
    locales: tuple[str, ...] = ()
    #: Per language, how many of its own words the step showed.
    language_evidence: tuple[tuple[str, int], ...] = ()
    #: Position in a multi-step form, 0 when unknown: from ``aria-current=step``
    #: (structure, any language) or a visible indicator ("Step 2 of 4",
    #: "Schritt 2 von 4", "第2步，共4步").
    step_now: int = 0
    step_total: int = 0
    #: Short visible texts that may be a step indicator, for the language
    #: layer to read (the perception does not parse words).
    step_texts: tuple[str, ...] = ()
    #: Links inside the form's area, with their context (``FormLink``).
    links: tuple[FormLink, ...] = ()
    #: Structural signs that this page is a test, not an application step:
    #: ``role=timer`` (an ARIA timer is shown), ``code-editor`` (an
    #: in-page code editor). Structure only, any language.
    test_signals: tuple[str, ...] = ()

    @property
    def has_form(self) -> bool:
        return self.purpose == "application" and bool(self.questions)

    def question(self, key: str) -> FormQuestion | None:
        for q in self.questions:
            if q.key == key:
                return q
        return None

    def all_refs(self) -> list[ControlRef]:
        """Every control of every question, in question order."""
        refs: list[ControlRef] = []
        for q in self.questions:
            refs.extend(q.controls)
        return refs


@dataclass(frozen=True)
class ControlState:
    """A live read-back of one control. Values are never logged.

    ``present`` False means the control could not be found (the page changed).
    ``value`` is what the control holds now: the text of a text field, the
    selected option's text of a select (empty for a placeholder), the checked
    state rendered as "true"/"false" for a checkbox or radio input, or the
    visible text of a custom combobox's selection.
    """

    present: bool
    visible: bool = False
    value: str = ""
    checked: bool | None = None
    files: int = 0
    disabled: bool = False
    invalid: bool = False
    value_missing: bool | None = None
    message: str = ""
    #: The control itself is shown (``visible`` may be True through its
    #: label: a radio or checkbox drawn by a styled label over a hidden
    #: input). None when the reader did not say.
    own_visible: bool | None = None
    #: The read itself failed (the page script raised): presence and
    #: visibility are UNKNOWN, not "absent" — a required question whose state
    #: could not be read is never treated as handled.
    read_failed: bool = False

    @property
    def filled(self) -> bool:
        """The control holds an answer (a checked box, a file, a value)."""
        if self.checked is not None:
            return bool(self.checked)
        if self.files:
            return True
        return bool(self.value.strip())


ABSENT = ControlState(present=False)
