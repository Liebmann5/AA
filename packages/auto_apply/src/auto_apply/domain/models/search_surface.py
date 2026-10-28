"""What a search surface accepts — the catalog's typed vocabulary.

This model is the single source of truth for "what can this search bar or
search URL do", shared by AA's automated engine strategies
(engine_strategies.py) and the user-facing query builder (turns 1-3 of the
query-builder chain). It used to live as three hardcoded maps in
engine_strategies.py; the byte-identity pin in
tests/adapters/test_engine_url_byte_identity.py proves the move changed no
automation output.

Verification is data, not prose. Every operator and URL option records a
status (vendor / measured / third_party / unverified), a source, and — for
"measured" — a date. An unverified capability is recorded so its absence from
the offered set is deliberate; it is never offered and never composed. A
second axis, ``composable``, separates "is it verified" from "can AA's
composer write it today", so a vendor-documented operator the builder cannot
emit yet is recorded honestly instead of being offered.

Unknown fields are a load error (extra="forbid"): a typo in bundled data
fails loudly at load time, never silently passes. There is no hidden in-code
fallback table anywhere in this design (the pay-transparency loader's silent
fallback is a known defect, deliberately not copied).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VerificationStatus(str, Enum):
    """How AA knows a capability works. See the module docstring."""

    VENDOR = "vendor"
    MEASURED = "measured"
    THIRD_PARTY = "third_party"
    UNVERIFIED = "unverified"


#: Statuses the builder may offer by default. Unverified is never offered.
OFFERED_STATUSES = frozenset(
    {
        VerificationStatus.VENDOR,
        VerificationStatus.MEASURED,
        VerificationStatus.THIRD_PARTY,
    }
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CitedSpec(_Frozen):
    """The evidence fields every catalog entry carries."""

    status: VerificationStatus
    source: str = ""
    verified_on: str | None = None
    caveats: tuple[str, ...] = ()
    composable: bool = True

    @model_validator(mode="after")
    def _measured_needs_a_date(self) -> "CitedSpec":
        if self.status is VerificationStatus.MEASURED and not self.verified_on:
            raise ValueError(
                "status 'measured' requires verified_on — a measurement without "
                "a date is a claim, not a measurement"
            )
        return self


class OperatorSpec(CitedSpec):
    """One typed-search operator (e.g. site:, phrase quoting, intitle:)."""

    name: str
    label: str
    explanation: str
    syntax: str
    channel: Literal["typed", "url", "both"] = "typed"
    accepts: str = "text"


class UrlOptionSpec(CitedSpec):
    """One option a surface accepts in its address (e.g. Google's tbs)."""

    name: str
    option: str
    label: str
    explanation: str
    channel: Literal["url", "both"] = "url"
    value_format: str = "{code}"
    codes: dict[str, str] = Field(default_factory=dict)
    option_labels: dict[str, str] = Field(default_factory=dict)
    typed_equivalent: str | None = None
    typed_equivalent_note: str = ""
    merge: Literal["comma", "append"] = "comma"
    free_form: bool = False

    @model_validator(mode="after")
    def _codes_and_free_form_agree(self) -> "UrlOptionSpec":
        if self.free_form and self.codes:
            raise ValueError("a free-form option takes the value verbatim; codes must be empty")
        if not self.free_form and not self.codes:
            raise ValueError("a coded option needs at least one code")
        return self


class TemplateParameterSpec(_Frozen):
    """One ordered URL parameter: a static value, or the query/location."""

    name: str
    value: str | None = None
    source: Literal["query", "location"] | None = None


class UrlTemplateSpec(_Frozen):
    """How a search URL is built for one view of a surface."""

    base: str
    parameters: tuple[TemplateParameterSpec, ...] = ()
    date_parameter: str | None = None


class TextQuerySpec(_Frozen):
    """How typed search text is composed for a surface."""

    or_token: str | None = None
    or_uppercase: bool = True
    phrase_quote: str = '"'
    subject_group: str = "({content})"
    exclude_prefix: str = "-"
    max_words: int | None = None
    max_words_status: VerificationStatus | None = None
    max_words_source: str = ""

    @model_validator(mode="after")
    def _limit_needs_a_status(self) -> "TextQuerySpec":
        if self.max_words is not None and self.max_words_status is None:
            raise ValueError(
                "max_words needs max_words_status — a limit without a source "
                "class is a guess"
            )
        return self


class SearchSurfaceSpec(_Frozen):
    """Everything AA knows about one search surface."""

    name: str
    display_name: str
    kind: Literal["engine", "job_board"]
    homepage: str
    summary: str = ""
    usage_note: str = ""
    text_query: TextQuerySpec = Field(default_factory=TextQuerySpec)
    urls: dict[str, UrlTemplateSpec] = Field(default_factory=dict)
    default_url: str | None = None
    automation_url: str | None = None
    operators: tuple[OperatorSpec, ...] = ()
    url_options: tuple[UrlOptionSpec, ...] = ()

    @model_validator(mode="after")
    def _references_resolve(self) -> "SearchSurfaceSpec":
        if self.default_url is not None and self.default_url not in self.urls:
            raise ValueError(f"{self.name}: default_url {self.default_url!r} is not a url template")
        if self.automation_url is not None and self.automation_url not in self.urls:
            raise ValueError(f"{self.name}: automation_url {self.automation_url!r} is not a url template")
        for key, template in self.urls.items():
            if template.date_parameter is not None and not any(
                o.name == template.date_parameter and o.option == "date"
                for o in self.url_options
            ):
                raise ValueError(
                    f"{self.name}: url template {key!r} names date_parameter "
                    f"{template.date_parameter!r}, which no date url_option defines"
                )
        return self

    @model_validator(mode="after")
    def _any_of_needs_a_token(self) -> "SearchSurfaceSpec":
        for op in self.operators:
            if (
                op.name == "any_of"
                and op.composable
                and op.status is not VerificationStatus.UNVERIFIED
                and not self.text_query.or_token
            ):
                raise ValueError(
                    f"{self.name}: an offered any_of operator needs text_query.or_token"
                )
        return self
