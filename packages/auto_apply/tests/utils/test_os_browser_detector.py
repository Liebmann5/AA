import os
import pytest
from auto_apply.utils import os_browser_detector

# The `mocker` fixture is the star of this test file.

def test_detector_on_windows(mocker):
    """
    GIVEN: The OS is identified as Windows.
    AND: Certain browser executables "exist" on the filesystem.
    WHEN: `get_installed_browsers` is called.
    THEN: It should return the correct, priority-sorted list of browsers.
    """
    # ARRANGE
    # 1. Fake the OS identification.
    mocker.patch("platform.system", return_value="Windows")

    # 2. Fake the filesystem check (`os.path.exists`).
    # We use a `side_effect` function to return True only for specific paths.
    def fake_os_path_exists(path):
        # Simulate Firefox and Edge being installed
        if "Mozilla Firefox\\firefox.exe" in str(path):
            return True
        if "Microsoft\\Edge\\Application\\msedge.exe" in str(path):
            return True
        return False

    mocker.patch("os.path.exists", side_effect=fake_os_path_exists)

    # ACT
    installed_browsers = os_browser_detector.get_installed_browsers()

    # ASSERT
    # The result must be sorted according to BROWSER_PRIORITY, so 'firefox' comes before 'edge'.
    assert installed_browsers == ["firefox", "edge"]


def test_detector_on_macos(mocker):
    """
    GIVEN: The OS is identified as macOS.
    AND: Certain browser .app directories "exist".
    WHEN: `get_installed_browsers` is called.
    THEN: It should return the correct, priority-sorted list.
    """
    # ARRANGE
    mocker.patch("platform.system", return_value="Darwin") # macOS's system name

    def fake_os_path_exists(path):
        # Simulate Safari and Chrome being installed
        # Use os.path.join to construct paths that are correct for the OS running the test
        safari_path = os.path.join("/Applications", "Safari.app")
        chrome_path = os.path.join("/Applications", "Google Chrome.app")
        if str(path) == safari_path: return True
        if str(path) == chrome_path: return True
        return False
    mocker.patch("os.path.exists", side_effect=fake_os_path_exists)

    # ACT
    installed_browsers = os_browser_detector.get_installed_browsers()

    # ASSERT
    # Chrome has a higher priority than Safari.
    assert installed_browsers == ["chrome", "safari"]


def test_detector_on_linux(mocker):
    """
    GIVEN: The OS is identified as Linux.
    AND: Certain browser commands are "found" in the system PATH.
    WHEN: `get_installed_browsers` is called.
    THEN: It should return the correct, priority-sorted list.
    """
    # ARRANGE
    mocker.patch("platform.system", return_value="Linux")

    # Fake the `shutil.which` command, which checks for executables in the PATH.
    def fake_shutil_which(command):
        # Simulate firefox being found but chrome not
        if command == "firefox":
            return "/usr/bin/firefox" # Return a truthy value (a fake path)
        return None # Return a falsy value

    mocker.patch("shutil.which", side_effect=fake_shutil_which)

    # ACT
    installed_browsers = os_browser_detector.get_installed_browsers()

    # ASSERT
    assert installed_browsers == ["firefox"]


def test_returns_empty_list_when_no_browsers_found(mocker):
    """
    GIVEN: The OS is Windows, but no browser executables are found.
    WHEN: `get_installed_browsers` is called.
    THEN: It should return an empty list.
    """
    # ARRANGE
    mocker.patch("platform.system", return_value="Windows")
    # This mock will always return False, simulating no browsers installed.
    mocker.patch("os.path.exists", return_value=False)

    # ACT
    installed_browsers = os_browser_detector.get_installed_browsers()

    # ASSERT
    assert installed_browsers == []


# def test_sorting_logic_with_all_browsers(mocker):
#     """
#     GIVEN: An OS where all supported browsers are detected.
#     WHEN: `get_installed_browsers` is called.
#     THEN: The returned list must exactly match the `BROWSER_PRIORITY` order.
#     """
#     # ARRANGE
#     mocker.patch("platform.system", return_value="Windows")
#     # This mock simulates all browsers being installed.
#     mocker.patch("os.path.exists", return_value=True)

#     # ACT
#     installed_browsers = os_browser_detector.get_installed_browsers()

#     # ASSERT
#     # This tests the primary responsibility of the main function: sorting.
#     # We compare it directly against the priority list defined in the module.
#     assert installed_browsers == os_browser_detector.BROWSER_PRIORITY
def test_sorting_logic_with_all_browsers(mocker):
    mocker.patch("platform.system", return_value="Windows")

    # *** THE FIX IS HERE ***
    # This mock needs to be a little smarter to handle the Safari check
    def fake_exists(path):
        # On Windows, a path containing "Safari" should not exist.
        if "Safari" in str(path):
            return False
        return True
    mocker.patch("os.path.exists", side_effect=fake_exists)

    installed_browsers = os_browser_detector.get_installed_browsers()

    # The windows detector does not find safari, so the result should not include it
    assert installed_browsers == ["chrome", "firefox", "edge"]