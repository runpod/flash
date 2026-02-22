"""Flash build command - Package Flash applications for deployment."""

import ast
import importlib.util
import json
import logging
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python 3.9-3.10

from runpod_flash.core.resources.constants import MAX_TARBALL_SIZE_MB

from ..utils.ignore import get_file_tree, load_ignore_patterns
from .build_utils.handler_generator import HandlerGenerator
from .build_utils.lb_handler_generator import LBHandlerGenerator
from .build_utils.manifest import ManifestBuilder
from .build_utils.scanner import RemoteDecoratorScanner

logger = logging.getLogger(__name__)

console = Console()

# Constants
# Timeout for pip install operations (large packages like torch can take 5-10 minutes)
PIP_INSTALL_TIMEOUT_SECONDS = 600
# Timeout for ensurepip (lightweight operation, typically completes in <10 seconds)
ENSUREPIP_TIMEOUT_SECONDS = 30
# Timeout for version checks (should be instant)
VERSION_CHECK_TIMEOUT_SECONDS = 5

# RunPod Serverless platform specifications
# RunPod serverless runs on x86_64 Linux, regardless of build platform
# Support multiple manylinux versions (newer versions are backward compatible)
RUNPOD_PLATFORMS = [
    "manylinux_2_28_x86_64",  # glibc 2.28+ (newest, for Python 3.13+)
    "manylinux_2_17_x86_64",  # glibc 2.17+ (covers most modern packages)
    "manylinux2014_x86_64",  # glibc 2.17 (legacy compatibility)
]
RUNPOD_PYTHON_IMPL = "cp"  # CPython implementation

# Pip command identifiers
UV_COMMAND = "uv"
PIP_MODULE = "pip"


def _find_local_runpod_flash() -> Optional[Path]:
    """Find local runpod_flash source directory if available.

    Returns:
        Path to runpod_flash package directory, or None if not found or installed from PyPI
    """
    try:
        spec = importlib.util.find_spec("runpod_flash")

        if not spec or not spec.origin:
            return None

        # Get package directory (spec.origin is __init__.py path)
        pkg_dir = Path(spec.origin).parent

        # Skip if installed in site-packages (PyPI install)
        if "site-packages" in str(pkg_dir):
            return None

        # Must be development install
        return pkg_dir

    except Exception:
        return None


def _bundle_local_runpod_flash(build_dir: Path) -> bool:
    """Copy local runpod_flash source into build directory.

    Args:
        build_dir: Target build directory

    Returns:
        True if bundled successfully, False otherwise
    """
    flash_pkg = _find_local_runpod_flash()

    if not flash_pkg:
        console.print(
            "[yellow]⚠ Local runpod_flash not found or using PyPI install[/yellow]"
        )
        return False

    # Copy runpod_flash to build
    dest = build_dir / "runpod_flash"
    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(
        flash_pkg,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )

    console.print(f"[cyan]✓ Bundled local runpod_flash from {flash_pkg}[/cyan]")
    return True


def _extract_runpod_flash_dependencies(flash_pkg_dir: Path) -> list[str]:
    """Extract runtime dependencies from runpod_flash's pyproject.toml.

    When bundling local runpod_flash source, we need to also install its dependencies
    so they're available in the build environment.

    Args:
        flash_pkg_dir: Path to runpod_flash package directory (src/runpod_flash)

    Returns:
        List of dependency strings, empty list if parsing fails
    """
    try:
        # Navigate from runpod_flash package to project root
        # flash_pkg_dir is src/runpod_flash, need to go up 2 levels to reach project root
        project_root = flash_pkg_dir.parent.parent
        pyproject_path = project_root / "pyproject.toml"

        if not pyproject_path.exists():
            console.print(
                "[yellow]⚠ runpod_flash pyproject.toml not found, "
                "dependencies may be missing[/yellow]"
            )
            return []

        # Parse TOML
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        # Extract dependencies from [project.dependencies]
        dependencies = data.get("project", {}).get("dependencies", [])

        if dependencies:
            console.print(
                f"[dim]Found {len(dependencies)} runpod_flash dependencies to install[/dim]"
            )

        return dependencies

    except Exception as e:
        console.print(
            f"[yellow]⚠ Failed to parse runpod_flash dependencies: {e}[/yellow]"
        )
        return []


def _remove_runpod_flash_from_requirements(build_dir: Path) -> None:
    """Remove runpod_flash from requirements.txt and clean up dist-info since we bundled source."""
    req_file = build_dir / "requirements.txt"

    if not req_file.exists():
        return

    lines = req_file.read_text().splitlines()
    filtered = [
        line
        for line in lines
        if not line.strip().startswith("runpod_flash")
        and not line.strip().startswith("runpod-flash")
    ]

    req_file.write_text("\n".join(filtered) + "\n")

    # Remove runpod_flash dist-info directory to avoid conflicts with bundled source
    # dist-info is created by pip install and can confuse Python's import system
    for dist_info in build_dir.glob("runpod_flash-*.dist-info"):
        if dist_info.is_dir():
            shutil.rmtree(dist_info)


def run_build(
    project_dir: Path,
    app_name: str,
    no_deps: bool = False,
    output_name: str | None = None,
    exclude: str | None = None,
    use_local_flash: bool = False,
    verbose: bool = False,
) -> Path:
    """Run the build process and return the artifact path.

    Contains all build steps: validate, collect files, manifest, deps, tarball.
    Always keeps the build directory — caller decides cleanup.

    Args:
        project_dir: Flash project directory
        app_name: Application name
        no_deps: Skip transitive dependencies during pip install
        output_name: Custom archive name (default: artifact.tar.gz)
        exclude: Comma-separated packages to exclude
        use_local_flash: Bundle local runpod_flash source
        verbose: Show archive and build directory paths in summary

    Returns:
        Path to the created artifact archive

    Raises:
        typer.Exit: On build failure (including when archive exceeds 500 MB)
    """
    if not validate_project_structure(project_dir):
        console.print("[red]Error:[/red] Not a valid Flash project")
        console.print("Run [bold]flash init[/bold] to create a Flash project")
        raise typer.Exit(1)

    # Create build directory first to ensure clean state before collecting files
    build_dir = create_build_directory(project_dir, app_name)

    # Parse exclusions
    excluded_packages = []
    if exclude:
        excluded_packages = [pkg.strip().lower() for pkg in exclude.split(",")]

    spec = load_ignore_patterns(project_dir)
    files = get_file_tree(project_dir, spec)

    try:
        copy_project_files(files, project_dir, build_dir)

        try:
            scanner = RemoteDecoratorScanner(build_dir)
            remote_functions = scanner.discover_remote_functions()

            manifest_builder = ManifestBuilder(
                app_name, remote_functions, scanner, build_dir=build_dir
            )
            manifest = manifest_builder.build()
            manifest_path = build_dir / "flash_manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2))

            lb_generator = LBHandlerGenerator(manifest, build_dir)
            lb_generator.generate_handlers()

            qb_generator = HandlerGenerator(manifest, build_dir)
            qb_generator.generate_handlers()

            flash_dir = project_dir / ".flash"
            deployment_manifest_path = flash_dir / "flash_manifest.json"
            shutil.copy2(manifest_path, deployment_manifest_path)

        except (ImportError, SyntaxError) as e:
            console.print(f"[red]Error:[/red] Code analysis failed: {e}")
            logger.exception("Code analysis failed")
            raise typer.Exit(1)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            logger.exception("Handler generation validation failed")
            raise typer.Exit(1)
        except Exception as e:
            logger.exception("Handler generation failed")
            console.print(f"[yellow]Warning:[/yellow] Handler generation failed: {e}")

    except typer.Exit:
        if build_dir.exists():
            shutil.rmtree(build_dir)
        raise
    except Exception as e:
        if build_dir.exists():
            shutil.rmtree(build_dir)
        console.print(f"[red]Error:[/red] Build failed: {e}")
        logger.exception("Build failed")
        raise typer.Exit(1)

    # install dependencies
    requirements = collect_requirements(project_dir, build_dir)

    # filter out excluded packages
    if excluded_packages:
        matched_exclusions = set()
        filtered_requirements = []

        for req in requirements:
            if should_exclude_package(req, excluded_packages):
                pkg_name = extract_package_name(req)
                if pkg_name in excluded_packages:
                    matched_exclusions.add(pkg_name)
            else:
                filtered_requirements.append(req)

        requirements = filtered_requirements

        unmatched = set(excluded_packages) - matched_exclusions
        if unmatched:
            console.print(
                f"[yellow]Warning:[/yellow] No packages matched exclusions: "
                f"{', '.join(sorted(unmatched))}"
            )

    if requirements:
        with console.status(f"Installing {len(requirements)} packages..."):
            success = install_dependencies(build_dir, requirements, no_deps)

        if not success:
            console.print("[red]Error:[/red] Failed to install dependencies")
            raise typer.Exit(1)

    # bundle local runpod_flash if requested
    if use_local_flash:
        if _bundle_local_runpod_flash(build_dir):
            _remove_runpod_flash_from_requirements(build_dir)

    # clean up and create archive
    cleanup_python_bytecode(build_dir)

    archive_name = output_name or "artifact.tar.gz"
    archive_path = project_dir / ".flash" / archive_name

    with console.status("Creating archive..."):
        create_tarball(build_dir, archive_path, app_name)

    size_mb = archive_path.stat().st_size / (1024 * 1024)

    # fail build if archive exceeds size limit
    if size_mb > MAX_TARBALL_SIZE_MB:
        console.print()
        console.print(
            f"[red]Error:[/red] Archive exceeds RunPod limit "
            f"({size_mb:.1f} MB / {MAX_TARBALL_SIZE_MB} MB)"
        )
        console.print(
            "  Use --exclude to skip packages in base image: "
            "[dim]flash deploy --exclude torch,torchvision,torchaudio[/dim]"
        )

        if archive_path.exists():
            archive_path.unlink()
        if build_dir.exists():
            shutil.rmtree(build_dir)

        raise typer.Exit(1)

    # Success summary
    _display_build_summary(
        archive_path, app_name, len(files), len(requirements), size_mb, verbose=verbose
    )

    return archive_path


def build_command(
    no_deps: bool = typer.Option(
        False, "--no-deps", help="Skip transitive dependencies during pip install"
    ),
    output_name: str | None = typer.Option(
        None, "--output", "-o", help="Custom archive name (default: artifact.tar.gz)"
    ),
    exclude: str | None = typer.Option(
        None,
        "--exclude",
        help="Comma-separated packages to exclude (e.g., 'torch,torchvision')",
    ),
    use_local_flash: bool = typer.Option(
        False,
        "--use-local-flash",
        help="Bundle local runpod_flash source instead of PyPI version (for development/testing)",
    ),
):
    """
    Build Flash application for debugging (build only, no deploy).

    Creates the build artifact and keeps the .build directory for inspection.
    For build + deploy, use 'flash deploy' instead.

    Examples:
      flash build                              # Build with all dependencies
      flash build --no-deps                    # Skip transitive dependencies
      flash build -o my-app.tar.gz             # Custom archive name
      flash build --exclude torch,torchvision  # Exclude large packages (assume in base image)
    """
    try:
        project_dir, app_name = discover_flash_project()

        run_build(
            project_dir=project_dir,
            app_name=app_name,
            no_deps=no_deps,
            output_name=output_name,
            exclude=exclude,
            use_local_flash=use_local_flash,
            verbose=True,
        )

    except KeyboardInterrupt:
        console.print("\n[yellow]Build cancelled by user[/yellow]")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red]Build failed:[/red] {e}")
        import traceback

        console.print(traceback.format_exc())
        raise typer.Exit(1)


def discover_flash_project() -> tuple[Path, str]:
    """
    Discover Flash project directory and app name.

    Returns:
        Tuple of (project_dir, app_name)

    Raises:
        typer.Exit: If not in a Flash project directory
    """
    project_dir = Path.cwd()
    app_name = project_dir.name

    return project_dir, app_name


def validate_project_structure(project_dir: Path) -> bool:
    """
    Validate that directory is a Flash project.

    A Flash project is any directory containing Python files. The
    RemoteDecoratorScanner validates that @remote functions exist.

    Args:
        project_dir: Directory to validate

    Returns:
        True if valid Flash project
    """
    py_files = list(project_dir.rglob("*.py"))
    if not py_files:
        console.print(f"[red]Error:[/red] No Python files found in {project_dir}")
        return False
    return True


def create_build_directory(project_dir: Path, app_name: str) -> Path:
    """
    Create .flash/.build/ directory.

    Args:
        project_dir: Flash project directory
        app_name: Application name (used for archive naming, not directory structure)

    Returns:
        Path to build directory
    """
    flash_dir = project_dir / ".flash"
    flash_dir.mkdir(exist_ok=True)

    build_dir = flash_dir / ".build"

    # Remove existing build directory
    if build_dir.exists():
        shutil.rmtree(build_dir)

    build_dir.mkdir(parents=True, exist_ok=True)

    return build_dir


def copy_project_files(files: list[Path], source_dir: Path, dest_dir: Path) -> None:
    """
    Copy project files to build directory.

    Args:
        files: List of files to copy
        source_dir: Source directory
        dest_dir: Destination directory
    """
    for file_path in files:
        # Get relative path
        rel_path = file_path.relative_to(source_dir)

        # Create destination path
        dest_path = dest_dir / rel_path

        # Create parent directories
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy file
        shutil.copy2(file_path, dest_path)


def cleanup_python_bytecode(build_dir: Path) -> None:
    """
    Remove Python bytecode files and __pycache__ directories from build directory.

    These files are generated during the build process when Python imports modules
    for validation. They are platform-specific and will be regenerated on the
    deployment platform, so including them is unnecessary.

    Args:
        build_dir: Build directory to clean up
    """
    # Remove all __pycache__ directories
    for pycache_dir in build_dir.rglob("__pycache__"):
        if pycache_dir.is_dir():
            shutil.rmtree(pycache_dir)

    # Remove any stray .pyc, .pyo, .pyd files
    for bytecode_pattern in ["*.pyc", "*.pyo", "*.pyd"]:
        for bytecode_file in build_dir.rglob(bytecode_pattern):
            if bytecode_file.is_file():
                bytecode_file.unlink()


def collect_requirements(project_dir: Path, build_dir: Path) -> list[str]:
    """
    Collect all requirements from requirements.txt and @remote decorators.

    Args:
        project_dir: Flash project directory
        build_dir: Build directory (to check for workers)

    Returns:
        List of requirement strings
    """
    requirements = []

    # Load requirements.txt
    req_file = project_dir / "requirements.txt"
    if req_file.exists():
        try:
            content = req_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith("#"):
                    requirements.append(line)
        except Exception as e:
            console.print(
                f"[yellow]Warning:[/yellow] Failed to read requirements.txt: {e}"
            )

    # Extract dependencies from @remote decorators
    workers_dir = build_dir / "workers"
    if workers_dir.exists():
        remote_deps = extract_remote_dependencies(workers_dir)
        requirements.extend(remote_deps)

    # Remove duplicates while preserving order
    seen = set()
    unique_requirements = []
    for req in requirements:
        if req not in seen:
            seen.add(req)
            unique_requirements.append(req)

    return unique_requirements


def extract_package_name(requirement: str) -> str:
    """
    Extract the package name from a requirement specification.

    Handles version specifiers, extras, and other pip requirement syntax.

    Args:
        requirement: Requirement string (e.g., "torch>=2.0.0", "numpy[extra]")

    Returns:
        Package name in lowercase (e.g., "torch", "numpy")

    Examples:
        >>> extract_package_name("torch>=2.0.0")
        "torch"
        >>> extract_package_name("numpy[extra]")
        "numpy"
        >>> extract_package_name("my-package==1.0.0")
        "my-package"
    """
    # Split on version specifiers, extras, and environment markers
    # This regex matches: < > = ! [ ; (common pip requirement delimiters)
    package_name = re.split(r"[<>=!\[;]", requirement)[0].strip().lower()
    return package_name


def should_exclude_package(requirement: str, exclusions: list[str]) -> bool:
    """
    Check if a requirement should be excluded based on package name matching.

    Uses exact package name matching (after normalization) to avoid false positives.

    Args:
        requirement: Requirement string (e.g., "torch>=2.0.0")
        exclusions: List of package names to exclude (lowercase)

    Returns:
        True if package should be excluded, False otherwise

    Examples:
        >>> should_exclude_package("torch>=2.0.0", ["torch", "numpy"])
        True
        >>> should_exclude_package("torch-vision==0.15.0", ["torch"])
        False  # torch-vision is different from torch
    """
    package_name = extract_package_name(requirement)
    return package_name in exclusions


def extract_remote_dependencies(workers_dir: Path) -> list[str]:
    """
    Extract dependencies from @remote decorators in worker files.

    Args:
        workers_dir: Path to workers directory

    Returns:
        List of dependency strings
    """
    dependencies = []

    for py_file in workers_dir.glob("**/*.py"):
        if py_file.name == "__init__.py":
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))

            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    for decorator in node.decorator_list:
                        if isinstance(decorator, ast.Call):
                            func_name = None
                            if isinstance(decorator.func, ast.Name):
                                func_name = decorator.func.id
                            elif isinstance(decorator.func, ast.Attribute):
                                func_name = decorator.func.attr

                            if func_name == "remote":
                                # Extract dependencies keyword argument
                                for keyword in decorator.keywords:
                                    if keyword.arg == "dependencies":
                                        if isinstance(keyword.value, ast.List):
                                            for elt in keyword.value.elts:
                                                if isinstance(elt, ast.Constant):
                                                    dependencies.append(elt.value)

        except Exception as e:
            console.print(
                f"[yellow]Warning:[/yellow] Failed to parse {py_file.name}: {e}"
            )

    return dependencies


def install_dependencies(
    build_dir: Path, requirements: list[str], no_deps: bool
) -> bool:
    """
    Install dependencies to build directory using pip or uv pip.

    Installs packages for Linux x86_64 platform to ensure compatibility with
    RunPod serverless, regardless of the build platform (macOS, Windows, Linux).

    Auto-installation behavior:
    - If standard pip is not available, it will be automatically installed via ensurepip
    - This modifies the current virtual environment (persists after build completes)
    - Standard pip is strongly preferred for cross-platform builds due to better
      manylinux compatibility (uv pip has known issues with manylinux_2_27+)

    Args:
        build_dir: Build directory (pip --target)
        requirements: List of requirements to install
        no_deps: If True, skip transitive dependencies

    Returns:
        True if successful
    """
    if not requirements:
        return True

    # Prefer standard pip over uv pip for cross-platform builds
    # Standard pip's --platform flag works correctly with manylinux tags
    # uv pip has known issues with manylinux_2_27/2_28 detection (uv issue #5106)
    pip_cmd = [sys.executable, "-m", PIP_MODULE]
    pip_available = False

    try:
        result = subprocess.run(
            pip_cmd + ["--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_CHECK_TIMEOUT_SECONDS,
        )
        if result.returncode == 0:
            pip_available = True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # If pip not available, install it using ensurepip
    # This modifies the current virtual environment
    if not pip_available:
        console.print(
            "[yellow]Standard pip not found. Installing pip for reliable cross-platform builds...[/yellow]"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ensurepip", "--upgrade"],
                capture_output=True,
                text=True,
                timeout=ENSUREPIP_TIMEOUT_SECONDS,
            )
            if result.returncode == 0:
                # Verify pip is now available
                result = subprocess.run(
                    pip_cmd + ["--version"],
                    capture_output=True,
                    text=True,
                    timeout=VERSION_CHECK_TIMEOUT_SECONDS,
                )
                if result.returncode == 0:
                    pip_available = True
                    console.print(
                        "[green]✓[/green] Standard pip installed successfully"
                    )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            console.print(f"[yellow]Warning:[/yellow] Failed to install pip: {e}")

    # If pip still not available, try uv pip (less reliable for cross-platform)
    if not pip_available:
        try:
            result = subprocess.run(
                [UV_COMMAND, PIP_MODULE, "--version"],
                capture_output=True,
                text=True,
                timeout=VERSION_CHECK_TIMEOUT_SECONDS,
            )
            if result.returncode == 0:
                pip_cmd = [UV_COMMAND, PIP_MODULE]
                pip_available = True
                console.print(
                    f"[yellow]Warning:[/yellow] Using '{UV_COMMAND} {PIP_MODULE}' which has known issues "
                    f"with newer manylinux tags (manylinux_2_27+)"
                )
                console.print(
                    "[yellow]This may fail for Python 3.13+ with newer packages (e.g., numpy 2.4+)[/yellow]"
                )
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    # If neither available, error out
    if not pip_available:
        console.print(
            f"[red]Error:[/red] Neither {PIP_MODULE} nor {UV_COMMAND} {PIP_MODULE} found"
        )
        console.print(f"\n[yellow]Install {PIP_MODULE} with one of:[/yellow]")
        console.print("  • python -m ensurepip --upgrade")
        console.print(f"  • {UV_COMMAND} {PIP_MODULE} install {PIP_MODULE}")
        return False

    # Get current Python version for compatibility
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

    # Determine if using uv pip or standard pip (different flag formats)
    is_uv_pip = pip_cmd[0] == UV_COMMAND

    # Build pip command with platform-specific flags for RunPod serverless
    cmd = pip_cmd + [
        "install",
        "--target",
        str(build_dir),
        "--python-version",
        python_version,
        "--upgrade",
    ]

    # Add platform-specific flags based on pip variant
    if is_uv_pip:
        # uv pip uses --python-platform with simpler values
        # Note: uv has known issues with manylinux_2_27+ detection (issue #5106)
        cmd.extend(
            [
                "--python-platform",
                "x86_64-unknown-linux-gnu",
                "--no-build",  # Don't build from source, use binary wheels only
            ]
        )
    else:
        # Standard pip uses --platform with manylinux tags
        # Specify multiple platforms for broader compatibility
        for platform in RUNPOD_PLATFORMS:
            cmd.extend(["--platform", platform])
        cmd.extend(
            [
                "--implementation",
                RUNPOD_PYTHON_IMPL,
                "--only-binary=:all:",
            ]
        )

    if no_deps:
        cmd.append("--no-deps")

    cmd.extend(requirements)

    # Log platform targeting info
    if is_uv_pip:
        platform_str = "x86_64-unknown-linux-gnu"
    else:
        platform_str = f"{len(RUNPOD_PLATFORMS)} manylinux variants"
    logger.debug(f"Installing for: {platform_str}, Python {python_version}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PIP_INSTALL_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            console.print(f"[red]pip install failed:[/red]\n{result.stderr}")
            return False

        return True

    except subprocess.TimeoutExpired:
        console.print(
            f"[red]pip install timed out ({PIP_INSTALL_TIMEOUT_SECONDS} seconds)[/red]"
        )
        return False
    except Exception as e:
        console.print(f"[red]pip install error:[/red] {e}")
        return False


def create_tarball(build_dir: Path, output_path: Path, app_name: str) -> None:
    """
    Create gzipped tarball of build directory.

    Args:
        build_dir: Build directory to archive
        output_path: Output archive path
        app_name: Application name (unused, for compatibility)
    """
    # Remove existing archive
    if output_path.exists():
        output_path.unlink()

    # Create tarball with build directory contents at root level
    with tarfile.open(output_path, "w:gz") as tar:
        tar.add(build_dir, arcname=".")


def cleanup_build_directory(build_base: Path) -> None:
    """
    Remove build directory.

    Args:
        build_base: .build directory to remove
    """
    if build_base.exists():
        shutil.rmtree(build_base)


def _display_build_summary(
    archive_path: Path,
    app_name: str,
    file_count: int,
    dep_count: int,
    size_mb: float,
    verbose: bool = False,
):
    """Display build summary."""
    console.print(
        f"[green]Built[/green] [bold]{app_name}[/bold]  "
        f"[dim]{file_count} files, {dep_count} deps, {size_mb:.1f} MB[/dim]"
    )
    if verbose:
        console.print(f"  [dim]Archive:[/dim]  {archive_path}")
        build_dir = archive_path.parent / ".build"
        if build_dir.exists():
            console.print(f"  [dim]Build:[/dim]    {build_dir}")
