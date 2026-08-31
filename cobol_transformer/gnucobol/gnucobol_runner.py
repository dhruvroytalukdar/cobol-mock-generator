"""Compile and run transformed programs with GnuCOBOL.

On Windows ``cobc`` lives inside WSL, so commands are routed through ``wsl``
with Windows paths translated to ``/mnt/<drive>/...``.  Compiler output is
surfaced verbatim -- a failure must be visible, never swallowed.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CompileResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    command: List[str] = field(default_factory=list)
    binary: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-4000:],
            "command": self.command,
        }


def to_wsl_path(path: str) -> str:
    """``C:\\a\\b`` -> ``/mnt/c/a/b``; already-POSIX paths pass through."""
    p = os.path.abspath(path).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        return f"/mnt/{m.group(1).lower()}/{m.group(2)}"
    return p


class GnuCobolRunner:
    """Drives ``cobc``, directly or through WSL."""

    def __init__(self, use_wsl: Optional[bool] = None, cobc: str = "cobc") -> None:
        if use_wsl is None:
            use_wsl = platform.system() == "Windows" and shutil.which("cobc") is None
        self.use_wsl = use_wsl
        self.cobc = cobc

    def _wrap(self, args: List[str]) -> List[str]:
        if self.use_wsl:
            return ["wsl", "-e"] + args
        return args

    def available(self) -> bool:
        try:
            proc = subprocess.run(
                self._wrap([self.cobc, "--version"]),
                capture_output=True, text=True, timeout=60,
            )
            return proc.returncode == 0
        except Exception:
            return False

    def compile(
        self,
        source: str,
        output: Optional[str] = None,
        extra_flags: Optional[List[str]] = None,
        executable: bool = True,
    ) -> CompileResult:
        """Compile ``source``; returns the result rather than raising."""
        src = to_wsl_path(source) if self.use_wsl else os.path.abspath(source)
        out = None
        if output:
            out = to_wsl_path(output) if self.use_wsl else os.path.abspath(output)

        args = [self.cobc]
        args.append("-x" if executable else "-m")
        # -free is wrong for this corpus: it is fixed-format, 80-column source.
        args += ["-std=default", "-Wno-unfinished"]
        if extra_flags:
            args += extra_flags
        if out:
            args += ["-o", out]
        args.append(src)

        cmd = self._wrap(args)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return CompileResult(False, -1, "", "cobc timed out", cmd)
        return CompileResult(
            ok=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            command=cmd,
            binary=output,
        )

    def run(self, binary: str, timeout: int = 60) -> CompileResult:
        """Execute a compiled program."""
        target = to_wsl_path(binary) if self.use_wsl else os.path.abspath(binary)
        cmd = self._wrap([target])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            return CompileResult(
                False, -1,
                (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                f"program timed out after {timeout}s (possible infinite loop)",
                cmd,
            )
        return CompileResult(
            ok=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            command=cmd,
        )
