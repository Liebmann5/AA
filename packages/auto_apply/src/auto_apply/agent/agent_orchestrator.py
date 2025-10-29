import logging
from pathlib import Path
from .states.base_state import BaseState
from .states.discovering_state import DiscoveringState
from .states.vetting_state import VettingState
from .states.applying_state import ApplyingState
from ..user_data import JobStateManager, JobStatus

logger = logging.getLogger(__name__)

class AgentOrchestrator:
    """Manages the state-driven lifecycle of the job application agent."""

    def __init__(self):
        self.context = {
            "discovered_jobs": [],
            "jobs_to_apply": [],
            "applications_completed": 0,
            "applications_failed": 0,
        }

        self.states = {
            "DISCOVERING": DiscoveringState(self.context),
            "VETTING": VettingState(self.context),
            "APPLYING": ApplyingState(self.context),
        }

        self.current_state: BaseState = self.states["DISCOVERING"]

        # Self-healing logic
        self._reset_stale_jobs()

    def _reset_stale_jobs(self) -> None:
        """Resets jobs from a previous run that were stuck in 'in_progress'."""
        logger.info("Checking for stale jobs from previous runs...")
        data_dir = Path.home() / ".auto_apply"
        stale_jobs_count = 0
        with JobStateManager(data_dir / "job_states.json") as state_manager:
            for url, data in state_manager.job_states.items():
                if data['status'] == JobStatus.APPLICATION_IN_PROGRESS.value:
                    state_manager.update_job_status(url, JobStatus.FOUND)
                    stale_jobs_count += 1
        if stale_jobs_count > 0:
            logger.warning(f"Reset {stale_jobs_count} stale jobs back to 'found' status.")

    def run(self):
        """Runs the agent's lifecycle until a terminal state is reached."""
        logger.info("--- Agent Orchestrator Starting ---")
        try:
            while self.current_state is not None:
                state_name = self.current_state.__class__.__name__
                logger.info("==> Entering State: %s <==", state_name)

                next_state_name = self.current_state.execute()

                if next_state_name:
                    self.current_state = self.states.get(next_state_name)
                else:
                    self.current_state = None
        except (KeyboardInterrupt, SystemExit):
            logger.warning("\n--- User interrupted workflow. Shutting down gracefully. ---")
        except Exception as e:
            logger.critical(
                "A fatal, unhandled error occurred in state '%s'. Aborting run. Error: %s",
                self.current_state.__class__.__name__ if self.current_state else "N/A", e, exc_info=True
            )
        finally:
            self._print_session_report()
            logger.info("--- Agent Orchestrator Shutdown Complete ---")

    def _print_session_report(self) -> None:
        """Logs a formatted summary of the completed session from the context."""
        logging.info("\n" + "="*50)
        logging.info("--- Session Report ---")
        logging.info(f"  Jobs Found in Search:      {len(self.context.get('discovered_jobs', []))}")
        logging.info(f"  New Jobs to Process:       {len(self.context.get('jobs_to_apply', []))}")
        logging.info(f"  Applications Completed:    {self.context.get('applications_completed', 0)}")
        logging.info(f"  Applications Failed:       {self.context.get('applications_failed', 0)}")
        logging.info("="*50 + "\n")