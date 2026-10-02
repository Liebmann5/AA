"""ReplayService — read a corpus, replay it, write the artifact (item 7).

The replay itself is pure (domain/services/replay.py). This service does the
two things around it that touch the outside world, through ports: reading
the corpus and writing the result. It also writes ``environment.json`` — the
Python version and operating system the replay ran on — beside the artifact
and OUTSIDE its digests: the claim is that the artifact is the same
everywhere, and recording where it ran must not make it differ.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from auto_apply.domain.models.replay import ReplayReport
from auto_apply.domain.ports.replay_port import ReplayArtifactSinkPort, ReplayCorpusPort
from auto_apply.domain.services.replay import replay_corpus

__all__ = ["ReplayService", "ARTIFACT_FILES"]

#: The files every replay writes. replay.jsonl and manifest.json are the
#: result; environment.json is a note about the run, not part of it.
ARTIFACT_FILES = ("replay.jsonl", "manifest.json", "environment.json")


class ReplayService:
    """Corpus in, artifact out."""

    def __init__(
        self,
        corpus: ReplayCorpusPort,
        sink_for: Callable[[str], ReplayArtifactSinkPort],
        aa_version: str,
        environment: Mapping[str, str],
    ) -> None:
        """
        Args:
            corpus: Where the kept page copies come from.
            sink_for: corpus digest -> where to write (so a default folder
                can be named after the corpus it replays).
            aa_version: The running AA version (part of the result).
            environment: Python and OS facts for environment.json.
        """
        self._corpus = corpus
        self._sink_for = sink_for
        self._aa_version = aa_version
        self._environment = dict(environment)

    def run(self) -> ReplayReport:
        corpus = self._corpus.read()
        output = replay_corpus(corpus, aa_version=self._aa_version)
        environment = dict(self._environment)
        environment["note"] = (
            "Where this replay ran. Not part of the result: replay.jsonl and "
            "manifest.json are the same on every machine for the same corpus "
            "and AA version."
        )
        files = {
            "replay.jsonl": output.records,
            "manifest.json": output.manifest,
            "environment.json": (
                json.dumps(environment, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8"),
        }
        location = self._sink_for(output.corpus_digest).write(files)
        counts: dict[str, int] = {}
        for line in output.records.splitlines():
            for signal in json.loads(line)["signals"]:
                counts[signal["signal_type"]] = counts.get(signal["signal_type"], 0) + 1
        return ReplayReport(
            output=output,
            location=location,
            signals_by_type=tuple(sorted(counts.items())),
        )
