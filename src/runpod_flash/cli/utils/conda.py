"""Conda environment management utilities."""

import subprocess
from typing import List, Tuple
from rich.console import Console

console = Console()


def check_conda_available() -> bool:
    """Check if conda is available on the system."""
    try:
        result = subprocess.run(
            ["conda", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def create_conda_environment(
    env_name: str, python_version: str = "3.11"
) -> Tuple[bool, str]:
    """
    Create a new conda environment.

    Args:
        env_name: Name of the conda environment
        python_version: Python version to use

    Returns:
        Tuple of (success, message)
    """
    try:
        console.print(f"Creating conda environment: {env_name}")

        result = subprocess.run(
            ["conda", "create", "-n", env_name, f"python={python_version}", "-y"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        if result.returncode == 0:
            return True, f"Conda environment '{env_name}' created successfully"
        else:
            return False, f"Failed to create environment: {result.stderr}"

    except subprocess.TimeoutExpired:
        return False, "Environment creation timed out"
    except Exception as e:
        return False, f"Error creating environment: {e}"


def install_packages_in_env(
    env_name: str, packages: List[str], use_pip: bool = True
) -> Tuple[bool, str]:
    """
    Install packages in a conda environment.

    Args:
        env_name: Name of the conda environment
        packages: List of packages to install
        use_pip: If True, use pip install; otherwise use conda install

    Returns:
        Tuple of (success, message)
    """
    try:
        console.print(f"Installing packages: {', '.join(packages)}")

        if use_pip:
            # Use conda run to execute pip in the environment
            cmd = [
                "conda",
                "run",
                "-n",
                env_name,
                "pip",
                "install",
            ] + packages
        else:
            cmd = ["conda", "install", "-n", env_name, "-y"] + packages

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes timeout
        )

        if result.returncode == 0:
            return True, "Packages installed successfully"
        else:
            return False, f"Failed to install packages: {result.stderr}"

    except subprocess.TimeoutExpired:
        return False, "Package installation timed out"
    except Exception as e:
        return False, f"Error installing packages: {e}"


def environment_exists(env_name: str) -> bool:
    """Check if a conda environment exists."""
    try:
        result = subprocess.run(
            ["conda", "env", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            # Check if environment name appears in the output
            return env_name in result.stdout
        return False

    except Exception:
        return False


def get_activation_command(env_name: str) -> str:
    """Get the command to activate the conda environment."""
    return f"conda activate {env_name}"
