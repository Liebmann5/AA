"""The default tool set. One import, one registry, no globals mutated."""

from __future__ import annotations

from pagecomp.registry import Registry
from pagecomp.tools import (
    arrival,
    controls,
    family,
    formread,
    forms,
    joblist,
    listing,
    pagetext,
    records,
    structured,
    verdict,
    views,
    visibility,
)

MODULES = (visibility, pagetext, structured, forms, formread, verdict, records, listing,
           joblist, family, arrival, controls, views)


def default_registry() -> Registry:
    reg = Registry()
    for m in MODULES:
        reg.register(m.TOOL)
    reg.check_acyclic()
    return reg
