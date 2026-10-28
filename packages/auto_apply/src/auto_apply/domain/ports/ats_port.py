"""Defines the contract for ATS platform identification and description.

``ATSDescriptor`` is the single source of truth for every platform-specific
selector and signal that the ApplicationEngine needs. Descriptors are loaded
at startup from ``resources/ats/*.yaml`` by the ``ATSRegistry`` adapter.

``ATSPort`` is the per-platform Protocol.  The registry is not itself an
``ATSPort``; it is a collection of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit


@runtime_checkable
class ATSRegistryPort(Protocol):
    """Contract for the ATS registry collection (as opposed to ATSPort,
    which describes a single platform). Concrete implementation: ATSRegistry
    in adapters/secondary/discovery/ats_registry.py.
    """

    def match(self, url: str) -> ATSDescriptor | None:
        """Return the ATSDescriptor whose url_patterns match *url*, if any."""
        ...

    def all_descriptors(self) -> list["ATSDescriptor"]:
        """Return every loaded descriptor, in load order."""
        ...

    def is_terminal_page(self, url: str) -> bool:
        """True when *url* matches a terminal pattern (success / confirm /
        closed) of any descriptor. Terminal pages are never apply-route
        destinations and never builder suggestions."""
        ...


@dataclass(frozen=True)
class ATSDescriptor:
    """Immutable description of a single ATS platform.

    Attributes:
        name: Canonical platform name, lowercase (e.g. ``"greenhouse"``).
        url_patterns: Glob-style patterns matched against the stripped URL
            (scheme removed).  ``*`` matches any run of characters including
            path separators.
        login_wall_signals: Lower-cased text snippets that indicate the page
            requires authentication before showing the application form.
        success_signals: Lower-cased text snippets that indicate the
            application was successfully submitted.
        form_root_selector: CSS selector for the element that roots the
            application form.  Used by ApplicationEngine to scope field
            searches.
        submit_button_selector: CSS selector for the final submit / next
            button on each form step.
        multi_step: ``True`` if the platform uses a wizard with multiple
            pages or steps before a final submission.
        hosts: The platform's own domains, lower-case. A host belongs to the
            platform when it equals one of these or is a subdomain of one.
            Research analysis groups destinations by platform through this
            field (item 2: the ATS-host confound). Empty means the
            descriptor claims no hosts.
    """

    name: str
    url_patterns: tuple[str, ...]
    login_wall_signals: tuple[str, ...]
    success_signals: tuple[str, ...]
    form_root_selector: str
    submit_button_selector: str
    multi_step: bool
    hosts: tuple[str, ...] = ()
    # ── Search and routing data (query-builder chain, call 2) ────────────
    # tenancy: how tenants are addressed — "subdomain" (acme.platform.com),
    # "path" (platform.com/acme), "opaque" (a path slug that is an ID, not a
    # name), "enterprise" (client identified by query/deep path only), or
    # "none" (no per-tenant addressing).
    tenancy: str = "none"
    # The site: restriction that scopes an engine search to this platform —
    # host, or host/path where the path is shared by every tenant
    # (e.g. "bamboohr.com/careers", "jobs.gusto.com/boards"). Empty when the
    # platform has no usable restriction.
    search_restriction: str = ""
    # Evidence about the restriction: vendor | measured | third_party |
    # unverified — the same vocabulary as the search-surface catalog.
    search_restriction_status: str = "unverified"
    search_restriction_verified_on: str = ""
    search_restriction_source: str = ""
    # URL shapes that are terminal pages (success / confirm / closed): never
    # an apply-route destination, never a builder suggestion.
    terminal_patterns: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return (
            f"ATSDescriptor(name={self.name!r}, "
            f"multi_step={self.multi_step}, "
            f"patterns={len(self.url_patterns)})"
        )

    # ── Tenancy and search restrictions (pure: no I/O, no clock) ──────────

    @property
    def search_host(self) -> str:
        """The bare host of the search restriction (or of the first host)."""
        base = self.search_restriction or (self.hosts[0] if self.hosts else "")
        return base.split("/", 1)[0].lower()

    def _path_prefix_segments(self) -> list[str]:
        """The static path segments of the first url_pattern, up to the
        first wildcard — the part of the path BEFORE the tenant slug
        ("boards" in "jobs.gusto.com/boards/*")."""
        if not self.url_patterns or "/" not in self.url_patterns[0]:
            return []
        segments: list[str] = []
        for segment in self.url_patterns[0].split("/", 1)[1].split("/"):
            if "*" in segment:
                break
            if segment:
                segments.append(segment.lower())
        return segments

    def tenant_slug(self, url: str) -> str | None:
        """The tenant identifier for *url*, or None when there is none.

        subdomain: the label(s) before this platform's host
            ("holisticai" in "holisticai.bamboohr.com").
        path / opaque: the path segment right after the pattern's static
            prefix ("ziffdavis" in "jobs.jobvite.com/ziffdavis/job/123";
            "db_cae6…" on recruiterflow — opaque is the same shape with an
            ID instead of a company name).
        None for "none"/"enterprise" tenancy, an unrelated URL, or a URL
        with no tenant segment.
        """
        base_host = self.search_host
        if not base_host:
            return None
        try:
            parts = urlsplit(url if "://" in url else f"https://{url}")
        except ValueError:
            return None
        host = parts.netloc.lower().split("@")[-1].split(":")[0]
        if not host or not (host == base_host or host.endswith("." + base_host)):
            return None
        if self.tenancy == "subdomain":
            if host == base_host:
                return None
            return host[: -len(base_host)].rstrip(".") or None
        if self.tenancy in ("path", "opaque"):
            prefix = self._path_prefix_segments()
            segments = [s for s in parts.path.lower().split("/") if s]
            if segments[: len(prefix)] != prefix:
                return None
            remaining = segments[len(prefix):]
            return remaining[0] if remaining else None
        return None

    def search_restriction_for(self, url: str | None = None) -> str:
        """The site: restriction for this platform — its shared restriction
        by default, narrowed to one tenant when *url* is one of its tenant
        pages ("holisticai.bamboohr.com/careers", "jobs.lever.co/acme").
        Empty when the platform declares no hosts."""
        base = self.search_restriction or (self.hosts[0] if self.hosts else "")
        if not base or url is None:
            return base
        slug = self.tenant_slug(url)
        if not slug:
            return base
        if self.tenancy == "subdomain":
            try:
                host = urlsplit(url if "://" in url else f"https://{url}").netloc.lower()
            except ValueError:
                return base
            host = host.split("@")[-1].split(":")[0]
            if not host:
                return base
            suffix = (
                self.search_restriction.split("/", 1)[1]
                if "/" in self.search_restriction
                else ""
            )
            return f"{host}/{suffix}" if suffix else host
        if self.tenancy in ("path", "opaque"):
            prefix = "/".join(self._path_prefix_segments())
            host0 = self.search_host
            return f"{host0}/{prefix}/{slug}" if prefix else f"{host0}/{slug}"
        return base


@runtime_checkable
class ATSPort(Protocol):
    """Contract for a single-platform ATS adapter.

    A concrete implementation wraps exactly one ``ATSDescriptor`` and
    answers whether a given URL belongs to that platform.

    The ``ATSRegistry`` aggregates multiple ``ATSPort`` implementations
    (one per YAML file) and exposes a single ``match(url)`` entry-point.
    """

    def matches(self, url: str) -> bool:
        """Returns ``True`` if *url* belongs to this ATS platform."""
        ...

    def descriptor(self) -> ATSDescriptor:
        """Returns the full descriptor for this ATS platform."""
        ...