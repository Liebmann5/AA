import logging
from pathlib import Path
from .base_state import BaseState
from ...data_processing import DataFilter
from ...user_data import AppliedJobsManager, JobStateManager

logger = logging.getLogger(__name__)

class VettingState(BaseState):
    """The state responsible for filtering and validating discovered jobs."""

    def execute(self) -> str | None:
        logger.info("Starting job vetting phase...")

        discovered_jobs = self.context.get("discovered_jobs", [])
        if not discovered_jobs:
            logger.info("No jobs were discovered. Ending run.")
            return None

        data_dir = Path.home() / ".auto_apply"

        with AppliedJobsManager(data_dir / "applied_jobs.json") as applied_manager, \
             JobStateManager(data_dir / "job_states.json") as state_manager:

            # --- Data Filtering ---
            data_filter = DataFilter(applied_manager)
            actionable_jobs = data_filter.filter_results(discovered_jobs)

            # --- State Update ---
            state_manager.add_new_jobs(actionable_jobs)
            jobs_to_apply = state_manager.get_jobs_to_apply_for()

        self.context["jobs_to_apply"] = jobs_to_apply

        logger.info("%d jobs remain after vetting.", len(jobs_to_apply))

        if jobs_to_apply:
            return "APPLYING"

        logger.info("No new jobs to apply for in this session. Ending run.")
        return None