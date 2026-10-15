#!/usr/bin/env python3
"""Build the SPR-enabled Neonize native library for the active environment."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


NEONIZE_REPOSITORY = "https://github.com/Nauvalunesa/neonize.git"
NEONIZE_COMMIT = "596d5ac327f176a70472147f96d4dd674c67911c"
NEONIZE_VERSION = "0.5.2"


def run(command: list[str], *, cwd: Path | None = None, env=None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def generated_library_name() -> str:
    operating_system = platform.system().lower()
    architecture = platform.machine().lower()
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(architecture, architecture)
    extension = {"windows": "dll", "darwin": "dylib"}.get(operating_system, "so")
    return f"neonize-{operating_system}-{architecture}.{extension}"


def check_toolchain() -> None:
    try:
        output = run(["go", "version"])
    except FileNotFoundError as exc:
        message = "Go 1.26.0+ is required; install Go and run this script again."
        raise RuntimeError(message) from exc
    match = re.search(r"\bgo(\d+)\.(\d+)(?:\.(\d+))?\b", output)
    if not match:
        raise RuntimeError(f"Could not parse Go version: {output}")
    version = tuple(int(part or 0) for part in match.groups())
    if version < (1, 26, 0):
        raise RuntimeError(f"Go 1.26.0+ is required; found {output}")
    if not (shutil.which("gcc") or shutil.which("cc")):
        raise RuntimeError("A C compiler (gcc or cc) is required to build Neonize with CGO.")


def installed_neonize_directory() -> Path:
    try:
        neonize_distribution = distribution("neonize")
    except PackageNotFoundError as exc:
        message = "Install requirements.txt before building the Neonize SPR library."
        raise RuntimeError(message) from exc

    if neonize_distribution.version != NEONIZE_VERSION:
        raise RuntimeError(
            f"Expected Neonize {NEONIZE_VERSION}, found {neonize_distribution.version}. "
            "Install the pinned requirements.txt first."
        )

    direct_url = neonize_distribution.read_text("direct_url.json")
    if direct_url:
        try:
            source = json.loads(direct_url)
        except json.JSONDecodeError as exc:
            message = "Neonize direct_url.json is invalid; reinstall the pinned dependency."
            raise RuntimeError(message) from exc
        vcs_info = source.get("vcs_info", {})
        actual_commit = vcs_info.get("commit_id")
        if actual_commit and actual_commit != NEONIZE_COMMIT:
            raise RuntimeError(
                f"Neonize is installed from commit {actual_commit}, expected {NEONIZE_COMMIT}."
            )

    package_directory = Path(neonize_distribution.locate_file("neonize")).resolve()
    if not package_directory.is_dir():
        message = f"Could not locate the installed Neonize package at {package_directory}."
        raise RuntimeError(message)
    return package_directory


def verify_native_library(path: Path) -> None:
    native = ctypes.CDLL(str(path))
    get_version = native.GetVersion
    get_version.restype = ctypes.c_char_p
    version = get_version().decode("ascii")
    if version != NEONIZE_VERSION:
        raise RuntimeError(f"Built library reports Neonize {version}, expected {NEONIZE_VERSION}.")
    try:
        native.SendSPRMessage
    except AttributeError as exc:
        raise RuntimeError("Built Neonize library does not export SendSPRMessage.") from exc


def build() -> Path:
    check_toolchain()
    package_directory = installed_neonize_directory()
    library_name = generated_library_name()
    environment = os.environ.copy()
    environment["CGO_ENABLED"] = "1"

    with tempfile.TemporaryDirectory(prefix="utusan-neonize-spr-") as temporary_directory:
        source_directory = Path(temporary_directory) / "neonize-source"
        clone = ["git", "clone", "--filter=blob:none", "--no-checkout"]
        run([*clone, NEONIZE_REPOSITORY, str(source_directory)])
        run(["git", "checkout", "--quiet", "--detach", NEONIZE_COMMIT], cwd=source_directory)
        actual_commit = run(["git", "rev-parse", "HEAD"], cwd=source_directory)
        if actual_commit != NEONIZE_COMMIT:
            message = f"Fetched Neonize commit {actual_commit}, expected {NEONIZE_COMMIT}."
            raise RuntimeError(message)

        build_directory = source_directory / "goneonize"
        built_library = build_directory / library_name
        run(
            ["go", "build", "-buildmode=c-shared", "-ldflags=-s", "-o", library_name, "main.go"],
            cwd=build_directory,
            env=environment,
        )
        verify_native_library(built_library)

        destination = package_directory / library_name
        staged_destination = package_directory / f".{library_name}.new"
        try:
            shutil.copy2(built_library, staged_destination)
            os.replace(staged_destination, destination)
        finally:
            staged_destination.unlink(missing_ok=True)

    return destination


def main() -> int:
    try:
        destination = build()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        process_output = getattr(exc, "stdout", None)
        detail = process_output or str(exc)
        print(f"Neonize SPR build failed: {detail}", file=sys.stderr)
        return 1
    print(f"Neonize SPR native library is ready: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
