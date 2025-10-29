import pytest
from auto_apply.agent.agent_orchestrator import AgentOrchestrator
from auto_apply.agent.states.base_state import BaseState

# This is the path to the modules we need to mock.
DISCOVERING_STATE_PATH = "auto_apply.agent.agent_orchestrator.DiscoveringState"
VETTING_STATE_PATH = "auto_apply.agent.agent_orchestrator.VettingState"
APPLYING_STATE_PATH = "auto_apply.agent.agent_orchestrator.ApplyingState"


@pytest.fixture
def mock_states(mocker):
    """
    A fixture that replaces the concrete State classes with mocks.
    This allows us to test the AgentOrchestrator's transition logic in isolation.
    """
    # Create mock instances that conform to the BaseState interface
    mock_discovering = mocker.create_autospec(BaseState, instance=True)
    mock_vetting = mocker.create_autospec(BaseState, instance=True)
    mock_applying = mocker.create_autospec(BaseState, instance=True)

    # Patch the classes within the AgentOrchestrator module so that when it
    # creates its instances, it gets our mocks instead of the real ones.
    mocker.patch(DISCOVERING_STATE_PATH, return_value=mock_discovering)
    mocker.patch(VETTING_STATE_PATH, return_value=mock_vetting)
    mocker.patch(APPLYING_STATE_PATH, return_value=mock_applying)

    # Return the mock instances in a dictionary for easy access in tests
    return {
        "DISCOVERING": mock_discovering,
        "VETTING": mock_vetting,
        "APPLYING": mock_applying,
    }

def test_run_all_states_successfully(mock_states):
    """
    GIVEN: Each state is configured to successfully transition to the next.
    WHEN: The AgentOrchestrator's run() method is called.
    THEN: It should execute the DISCOVERING, VETTING, and APPLYING states in order.
    """
    # ARRANGE
    # Configure the return value of each state's 'execute' method to simulate
    # a successful "happy path" workflow.
    mock_states["DISCOVERING"].execute.return_value = "VETTING"
    mock_states["VETTING"].execute.return_value = "APPLYING"
    mock_states["APPLYING"].execute.return_value = None  # None signifies a terminal state

    agent = AgentOrchestrator()

    # ACT
    agent.run()

    # ASSERT
    # Verify that each state's main logic was called exactly once.
    mock_states["DISCOVERING"].execute.assert_called_once()
    mock_states["VETTING"].execute.assert_called_once()
    mock_states["APPLYING"].execute.assert_called_once()

def test_run_stops_if_vetting_finds_no_jobs(mock_states):
    """
    GIVEN: The VETTING state finds no actionable jobs.
    WHEN: The AgentOrchestrator runs.
    THEN: It should execute DISCOVERING and VETTING, but NOT APPLYING.
    """
    # ARRANGE
    # Simulate a scenario where vetting is the terminal state.
    mock_states["DISCOVERING"].execute.return_value = "VETTING"
    mock_states["VETTING"].execute.return_value = None  # Vetting finds no jobs and ends the run

    agent = AgentOrchestrator()

    # ACT
    agent.run()

    # ASSERT
    mock_states["DISCOVERING"].execute.assert_called_once()
    mock_states["VETTING"].execute.assert_called_once()

    # Crucially, assert that the APPLYING state was never entered.
    mock_states["APPLYING"].execute.assert_not_called()

def test_run_halts_on_state_exception(mock_states, caplog):
    """
    GIVEN: A state (e.g., VETTING) raises a critical exception.
    WHEN: The AgentOrchestrator runs.
    THEN: The orchestrator should catch the exception, log it, and gracefully terminate without proceeding to the next state.
    """
    # ARRANGE
    # Configure the VETTING state to simulate a crash.
    mock_states["DISCOVERING"].execute.return_value = "VETTING"
    mock_states["VETTING"].execute.side_effect = ValueError("A critical error in vetting")

    agent = AgentOrchestrator()

    # ACT
    # The run method should handle the exception internally and not crash the test.
    agent.run()

    # ASSERT
    mock_states["DISCOVERING"].execute.assert_called_once()
    mock_states["VETTING"].execute.assert_called_once()

    # The APPLYING state should never be reached.
    mock_states["APPLYING"].execute.assert_not_called()

    # Verify that the critical error was logged.
    assert "A fatal, unhandled error occurred in state 'BaseState'" in caplog.text
    assert "A critical error in vetting" in caplog.text