"""Talk to the CobolAstHttpServer, with a subprocess CLI fallback.

The HTTP server keeps one long-lived language-server session, so calling it
repeatedly avoids paying the multi-second JVM/Equinox boot for every program.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ..errors import AstUnavailableError
from .ast_model import AstDocument


@dataclass
class AstClientConfig:
    base_url: str = "http://127.0.0.1:4010"
    timeout: int = 240
    api_token: Optional[str] = None
    cli_script: Optional[str] = None   # path to cobol-ast-cli.bat/.sh for fallback


class HttpAstClient:
    """Primary AST backend."""

    def __init__(self, config: Optional[AstClientConfig] = None) -> None:
        self.config = config or AstClientConfig()

    def available(self) -> bool:
        try:
            req = urllib.request.Request(self.config.base_url + "/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return bool(payload.get("ok"))
        except Exception:
            return False

    def get_ast(self, source_text: str, filename_hint: str = "source.cbl") -> AstDocument:
        """Return the parsed AST, or raise ``AstUnavailableError``.

        The server answers 500 with ``{"ok": false, "error": ...}`` when its
        CICS validator rejects a command; that is reported as unavailable so the
        caller can fall back to text detection.
        """
        data = source_text.encode("utf-8")
        req = urllib.request.Request(
            self.config.base_url + "/generate-ast",
            data=data,
            method="POST",
        )
        req.add_header("Content-Type", "text/plain; charset=utf-8")
        req.add_header("X-Filename", os.path.basename(filename_hint))
        if self.config.api_token:
            req.add_header("Authorization", f"Bearer {self.config.api_token}")

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except ValueError:
                raise AstUnavailableError(
                    f"AST server HTTP {exc.code}: {body[:400]}"
                ) from exc
            raise AstUnavailableError(str(payload.get("error", body))[:600]) from exc
        except Exception as exc:
            raise AstUnavailableError(f"AST server unreachable: {exc}") from exc

        if not payload.get("ok"):
            raise AstUnavailableError(str(payload.get("error"))[:600])
        return AstDocument.from_json(payload, filename_hint)


class SubprocessAstClient:
    """Fallback backend that shells out to the one-shot CLI wrapper."""

    def __init__(self, cli_script: str, timeout: int = 300) -> None:
        self.cli_script = cli_script
        self.timeout = timeout

    def available(self) -> bool:
        return os.path.isfile(self.cli_script)

    def get_ast(self, source_text: str, filename_hint: str = "source.cbl") -> AstDocument:
        tmpdir = tempfile.mkdtemp(prefix="cobol-ast-")
        src = os.path.join(tmpdir, os.path.basename(filename_hint))
        out = os.path.join(tmpdir, "ast.json")
        with open(src, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source_text)
        cmd = [self.cli_script, "--quiet", "--output", out, src]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired as exc:
            raise AstUnavailableError(f"AST CLI timed out after {self.timeout}s") from exc
        if not os.path.isfile(out):
            raise AstUnavailableError(
                f"AST CLI failed (exit {proc.returncode}): {(proc.stderr or '')[:400]}"
            )
        with open(out, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return AstDocument.from_json(payload, filename_hint)
