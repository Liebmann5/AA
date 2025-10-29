from pathlib import Path
from auto_apply.core.proxy_manager import ProxyManager

# The `mocker` fixture comes from pytest-mock and is our tool for controlling randomness.
# The `tmp_path` fixture is from pytest and provides a clean temporary directory.

def test_load_proxies_from_valid_file(tmp_path: Path):
    """
    GIVEN: A proxy file exists with several proxies, blank lines, and whitespace.
    WHEN: A ProxyManager is instantiated with the path to that file.
    THEN: The manager should load only the valid, stripped proxy strings.
    """
    # ARRANGE
    proxy_file = tmp_path / "proxies.txt"
    # Create a file with varied content to test parsing logic.
    proxy_content = (
        "user1:pass1@host1:port1\n"
        " host2:port2 \n"  # With leading/trailing whitespace
        "\n"  # A blank line that should be ignored
        "host3:port3\n"
    )
    proxy_file.write_text(proxy_content)

    # ACT (Loading happens in the constructor)
    manager = ProxyManager(proxy_file=proxy_file)

    # ASSERT
    assert len(manager.proxies) == 3
    assert "user1:pass1@host1:port1" in manager.proxies
    # Assert that the whitespace was correctly stripped.
    assert "host2:port2" in manager.proxies
    assert "host3:port3" in manager.proxies


def test_manager_handles_non_existent_file_gracefully(tmp_path: Path):
    """
    GIVEN: A path to a proxy file that does not exist.
    WHEN: A ProxyManager is instantiated.
    THEN: It should not raise an error and its proxy list should be empty.
    """
    # ARRANGE
    non_existent_file = tmp_path / "no_proxies_here.txt"

    # ACT
    manager = ProxyManager(proxy_file=non_existent_file)

    # ASSERT
    assert manager.proxies == []


def test_manager_handles_empty_file_gracefully(tmp_path: Path):
    """
    GIVEN: An existing but empty proxy file.
    WHEN: A ProxyManager is instantiated.
    THEN: It should not raise an error and its proxy list should be empty.
    """
    # ARRANGE
    empty_file = tmp_path / "empty_proxies.txt"
    empty_file.touch() # Creates an empty file

    # ACT
    manager = ProxyManager(proxy_file=empty_file)

    # ASSERT
    assert manager.proxies == []


def test_get_proxy_returns_none_when_list_is_empty(tmp_path: Path):
    """
    GIVEN: A ProxyManager with no proxies loaded.
    WHEN: `get_proxy` is called.
    THEN: It should return None.
    """
    # ARRANGE
    manager = ProxyManager(proxy_file=tmp_path / "no_file.txt") # Will be empty

    # ACT
    proxy = manager.get_proxy()

    # ASSERT
    assert proxy is None


def test_get_proxy_returns_a_valid_proxy_from_the_list(tmp_path: Path):
    """
    GIVEN: A ProxyManager with a loaded list of proxies.
    WHEN: `get_proxy` is called.
    THEN: The returned value must be one of the strings from the loaded list.
    """
    # ARRANGE
    proxy_file = tmp_path / "proxies.txt"
    proxy_list = ["proxy1", "proxy2", "proxy3"]
    proxy_file.write_text("\n".join(proxy_list))
    manager = ProxyManager(proxy_file=proxy_file)

    # ACT
    chosen_proxy = manager.get_proxy()

    # ASSERT
    assert chosen_proxy in proxy_list


def test_get_proxy_uses_random_choice(mocker, tmp_path: Path):
    """
    GIVEN: A ProxyManager with a loaded list of proxies.
    WHEN: `get_proxy` is called.
    THEN: The `random.choice` function should be called exactly once with the proxy list.
    """
    # ARRANGE
    proxy_file = tmp_path / "proxies.txt"
    proxy_list = ["proxy1", "proxy2"]
    proxy_file.write_text("\n".join(proxy_list))
    manager = ProxyManager(proxy_file=proxy_file)

    # Use mocker to spy on the `random.choice` function. We tell it to return
    # a predictable value so our test is not random.
    mock_random_choice = mocker.patch("random.choice", return_value="proxy2")

    # ACT
    result = manager.get_proxy()

    # ASSERT
    # 1. Assert that our function returned the predictable value from the mock.
    assert result == "proxy2"

    # 2. Assert that the `random.choice` function was called exactly once.
    mock_random_choice.assert_called_once()

    # 3. (Advanced) Assert WHAT `random.choice` was called with.
    # This proves we passed our internal proxy list to the randomizer.
    mock_random_choice.assert_called_with(manager.proxies)