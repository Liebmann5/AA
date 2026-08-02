"""Discovery Math Auditor - logs insights into Discovery pipeline & Mathematical perception.

Guard: set environment variable AUDIT_DISCOVERY=1 to enable verbose logging.
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_ENABLED = os.environ.get("AUDIT_DISCOVERY", "0") == "1"


class DiscoveryMathAuditor:
    """Collection of static audit methods for mathematical job discovery.

    All methods are no-ops unless the AUDIT_DISCOVERY flag is set.
    """
    _ENABLED = _ENABLED

    @property
    def enabled(self) -> bool:
        """Whether records are being kept — satisfies ExtractionObserverPort.

        Reads the same class flag every static call site already reads, so
        instance use and static use agree by construction.
        """
        return bool(self._ENABLED)

    @staticmethod
    def audit_candidate_containers(containers: list[Any], source: str) -> None:
        if not DiscoveryMathAuditor._ENABLED or not containers:
            return
        logger.info("[AUDIT] Candidate containers for %s: count=%d", source, len(containers))
        for i, node in enumerate(containers):
            geom = getattr(node, 'geometry', None)
            area = geom.area if geom else 0
            ch_count = len(node.children) if hasattr(node, 'children') else 0
            logger.debug(
                "[AUDIT]   card %d: tag=%s area=%.1f children=%d depth=%d",
                i, node.tag, area, ch_count, node.depth,
            )

    @staticmethod
    def audit_structural_hash_groups(groups: dict[str, list[Any]], source: str) -> None:
        if not DiscoveryMathAuditor._ENABLED or not groups:
            return
        logger.info("[AUDIT] Structural hash groups for %s: total groups=%d", source, len(groups))
        for hash_val, nodes in groups.items():
            logger.debug(
                "[AUDIT]   group '%s' size=%d", hash_val, len(nodes),
            )
            for node in nodes:
                logger.debug(
                    "[AUDIT]     node: tag=%s depth=%d children=%d",
                    node.tag, node.depth, len(node.children),
                )

    @staticmethod
    def audit_extraction_attempt(job_data: dict[str, Any], success: bool, reason: str = "") -> None:
        if not DiscoveryMathAuditor._ENABLED:
            return
        if success:
            logger.info(
                "[AUDIT] Extraction SUCCESS: title='%s' company='%s' url='%s'",
                job_data.get('title', ''), job_data.get('company', ''), job_data.get('url', ''),
            )
        else:
            logger.info(
                "[AUDIT] Extraction FAILED: reason=%s partial_data=%s",
                reason, {k: v for k, v in job_data.items() if v},
            )

    @staticmethod
    def audit_geometry_cluster(cluster_text: list[str], page_title: str) -> None:
        if not DiscoveryMathAuditor._ENABLED:
            return
        logger.info(
            "[AUDIT] Text cluster (first 5): %s | page title: %s",
            cluster_text[:5], page_title,
        )

    @staticmethod
    def audit_validation_error(job_dict: dict[str, Any], error: str) -> None:
        if not DiscoveryMathAuditor._ENABLED:
            return
        logger.error(
            "[AUDIT] Validation error: %s | job_dict=%s", error, job_dict,
        )

    @staticmethod
    def audit_final_job_list(jobs: list[Any], provider: str) -> None:
        if not DiscoveryMathAuditor._ENABLED:
            return
        logger.info(
            "[AUDIT] Final job list for %s: count=%d", provider, len(jobs),
        )
        for i, job in enumerate(jobs):
            title = getattr(job, 'title', '') if hasattr(job, 'title') else job.get('title', '')
            company = getattr(job, 'company', '') if hasattr(job, 'company') else job.get('company', '')
            url = getattr(job, 'url', '') if hasattr(job, 'url') else job.get('url', '')
            logger.debug(
                "[AUDIT]   job %d: title='%s' company='%s' url='%s'",
                i, title, company, url,
            )

    @staticmethod
    def audit_text_extraction(node: Any, text: str, source: str) -> None:
        if not DiscoveryMathAuditor._ENABLED:
            return
        logger.debug(
            "[AUDIT] Text extraction from %s: tag=%s text_len=%d snippet='%s'",
            source, getattr(node, 'tag', 'unknown'), len(text), text[:80],
        )