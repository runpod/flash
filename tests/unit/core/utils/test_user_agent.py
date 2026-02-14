"""Tests for user_agent module."""

import platform
import re


def test_get_user_agent_format():
    """Test User-Agent string format matches expected pattern."""
    from runpod_flash.core.utils.user_agent import get_user_agent

    ua = get_user_agent()

    # Should match: "Runpod Flash/<version> (Python <py_version>; <OS>)"
    pattern = r"^Runpod Flash/[\w\.]+ \(Python [\d\.]+; \w+\)$"
    assert re.match(pattern, ua), f"User-Agent '{ua}' doesn't match expected format"


def test_get_user_agent_contains_version():
    """Test User-Agent includes version information."""
    from runpod_flash.core.utils.user_agent import get_user_agent

    ua = get_user_agent()

    # Should start with "Runpod Flash/"
    assert ua.startswith("Runpod Flash/"), (
        f"User-Agent should start with 'Runpod Flash/', got: {ua}"
    )

    # Should contain version (either real version or 'unknown')
    version_part = ua.split(" ")[2]  # "Runpod Flash/<version> (Python ..."
    assert version_part.startswith("(Python"), (
        "User-Agent should contain Python version"
    )


def test_get_user_agent_contains_python_version():
    """Test User-Agent includes Python version."""
    from runpod_flash.core.utils.user_agent import get_user_agent

    ua = get_user_agent()
    python_version = platform.python_version()

    assert f"Python {python_version}" in ua, (
        f"User-Agent should contain Python {python_version}"
    )


def test_get_user_agent_contains_os():
    """Test User-Agent includes OS name."""
    from runpod_flash.core.utils.user_agent import get_user_agent

    ua = get_user_agent()
    os_name = platform.system()

    assert os_name in ua, f"User-Agent should contain OS name {os_name}"


def test_get_user_agent_structure():
    """Test User-Agent has correct structure."""
    from runpod_flash.core.utils.user_agent import get_user_agent

    ua = get_user_agent()

    # Should have exactly one opening and closing parenthesis
    assert ua.count("(") == 1, "User-Agent should have exactly one opening parenthesis"
    assert ua.count(")") == 1, "User-Agent should have exactly one closing parenthesis"

    # Should have exactly one semicolon (separating Python version and OS)
    assert ua.count(";") == 1, "User-Agent should have exactly one semicolon"


def test_get_user_agent_consistency():
    """Test User-Agent is consistent across multiple calls."""
    from runpod_flash.core.utils.user_agent import get_user_agent

    ua1 = get_user_agent()
    ua2 = get_user_agent()

    assert ua1 == ua2, "User-Agent should be consistent across calls"
