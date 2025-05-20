# Copyright (c) 2021 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import asyncio
import tempfile
import shutil
import json
import pytest
from pathlib import Path
from yakut.util import EXIT_CODE_UNSUCCESSFUL
from tests.subprocess import Subprocess


async def _setup_test_env():
    server_root = tempfile.mkdtemp(".file_server", "root.")
    client_root = tempfile.mkdtemp(".file_client", "root.")
    print("SERVER ROOT:", server_root)
    print("CLIENT ROOT:", client_root)

    # Start file server in background
    srv_proc = Subprocess.cli(
        "file-server",
        server_root,
        environment_variables={"UAVCAN__UDP__IFACE": "127.0.0.1", "UAVCAN__NODE__ID": "42"},
    )
    await asyncio.sleep(5.0)  # Let the server initialize
    assert srv_proc.alive
    return server_root, client_root, srv_proc


async def _cleanup_test_env(server_root: str, client_root: str, srv_proc: Subprocess):
    srv_proc.wait(10.0, interrupt=True)
    await asyncio.sleep(2.0)
    shutil.rmtree(server_root, ignore_errors=True)
    shutil.rmtree(client_root, ignore_errors=True)


async def _run_client_command(command: str, *args: str) -> tuple[int, str, str]:
    """Helper to run file client commands with common configuration"""
    proc = Subprocess.cli(
        "-j",
        "file-client",
        command,
        *args,
        environment_variables={
            "UAVCAN__UDP__IFACE": "127.0.0.1",
            "UAVCAN__NODE__ID": "43",
        },
    )
    return proc.wait(10.0)


async def _unittest_file_client_basic_operations() -> None:
    """Test basic file operations: ls, touch, read, write, rm"""
    server_root, client_root, srv_proc = await _setup_test_env()
    try:
        # List empty directory
        exitcode, stdout, stderr = await _run_client_command("ls", "42", "/")
        print(stderr)
        assert exitcode == 0
        files = json.loads(stdout)
        print(files)
        assert isinstance(files, list)
        assert len(files) == 0  # Empty directory should show empty list

        # Create a test file
        exitcode, stdout, _ = await _run_client_command("touch", "42", "/test.txt")
        assert exitcode == 0

        # Verify file exists with ls
        exitcode, stdout, _ = await _run_client_command("ls", "42", "/")
        assert exitcode == 0
        files = json.loads(stdout)
        assert isinstance(files, list)
        assert any(f["name"] == "test.txt" for f in files)

        # Write content to file
        test_content = "Hello, World!"
        temp_file = Path(client_root) / "local_test.txt"
        temp_file.write_text(test_content)
        exitcode, _, _ = await _run_client_command("write", "42", str(temp_file), "/test.txt")
        assert exitcode == 0

        # Read back the content
        read_file = Path(client_root) / "read_test.txt"
        exitcode, _, _ = await _run_client_command("read", "42", "/test.txt", str(read_file))
        assert exitcode == 0
        assert read_file.read_text() == test_content

        # Copy the file
        exitcode, _, _ = await _run_client_command("cp", "42", "/test.txt", "/copy.txt")
        assert exitcode == 0

        # Verify both files exist
        exitcode, stdout, _ = await _run_client_command("ls", "42", "/")
        assert exitcode == 0
        print(stdout)
        files = json.loads(stdout)
        assert isinstance(files, list)
        filenames = [f["name"] for f in files]
        assert all(name in filenames for name in ["test.txt", "copy.txt"])

        # Move the source file
        exitcode, _, _ = await _run_client_command("mv", "42", "/test.txt", "/moved.txt")
        assert exitcode == 0

        # Verify file list after move
        exitcode, stdout, _ = await _run_client_command("ls", "42", "/")
        assert exitcode == 0
        files = json.loads(stdout)
        assert isinstance(files, list)
        filenames = [f["name"] for f in files]
        assert all(name in filenames for name in ["moved.txt", "copy.txt"])
        assert "test.txt" not in filenames

        # Remove the file
        exitcode, _, _ = await _run_client_command("rm", "42", "/moved.txt")
        assert exitcode == 0

        # Verify file is gone
        exitcode, stdout, _ = await _run_client_command("ls", "42", "/")
        assert exitcode == 0
        files = json.loads(stdout)
        assert isinstance(files, list)
        assert not any(f["name"] == "moved.txt" for f in files)

    finally:
        await _cleanup_test_env(server_root, client_root, srv_proc)


async def _unittest_file_client_error_cases() -> None:
    """Test error handling in file client operations"""
    server_root, client_root, srv_proc = await _setup_test_env()
    try:
        # Try to read non-existent file
        exitcode, _, stderr = await _run_client_command("read", "42", "/nonexistent.txt", str(Path(client_root) / "local.txt"))
        assert exitcode == EXIT_CODE_UNSUCCESSFUL
        assert "not found" in stderr.lower()

        # Try to remove non-existent file (warning)
        exitcode, _, stderr = await _run_client_command("rm", "42", "/nonexistent.txt")
        assert exitcode == 0
        assert "not found" in stderr.lower()

        # Create a file then try invalid operations
        exitcode, _, _ = await _run_client_command("touch", "42", "/test.txt")
        assert exitcode == 0

        # Try to create file that already exists (should work, just updates timestamp)
        exitcode, _, _ = await _run_client_command("touch", "42", "/test.txt")
        assert exitcode == 0

        # Try to move to invalid destination (root is read-only)
        exitcode, _, stderr = await _run_client_command("mv", "42", "/test.txt", "//test.txt")
        assert exitcode == EXIT_CODE_UNSUCCESSFUL

        # Try to write with invalid node ID
        exitcode, _, stderr = await _run_client_command("write", "999", "/test.txt", str(Path(client_root) / "local.txt"))
        assert exitcode == EXIT_CODE_UNSUCCESSFUL

    finally:
        await _cleanup_test_env(server_root, client_root, srv_proc)
