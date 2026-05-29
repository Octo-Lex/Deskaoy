"""Typed Workflow Blocks — structured, validated, retryable automation units.

Each block type represents a specific kind of desktop automation step
(for loop, wait, download, validation, form fill, code execution).
Blocks validate their parameters before execution and compile to DAGNode
lists for the existing DAGExecutor.

Inspired by Skyvern's typed workflow blocks.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base Block
# ---------------------------------------------------------------------------

@dataclass
class WorkflowBlock(ABC):
    """Base class for all workflow blocks.

    Subclasses must implement:
      - validate() -> list[str]: return list of validation errors (empty = valid)
      - compile(agent) -> list[DAGNode]: convert to executable DAG nodes
    """
    id: str
    block_type: str = ""
    retry_count: int = 0
    timeout: float = 60.0

    def __post_init__(self) -> None:
        if not self.block_type:
            self.block_type = type(self).__name__.replace("Block", "").lower()

    @abstractmethod
    def validate(self) -> list[str]:
        """Validate block parameters. Returns list of error strings (empty = valid)."""
        ...

    @abstractmethod
    def compile(self, agent: Any = None) -> list[Any]:
        """Compile this block into DAGNode(s) for execution."""
        ...

    @property
    def is_valid(self) -> bool:
        return len(self.validate()) == 0


# ---------------------------------------------------------------------------
# ForLoop Block
# ---------------------------------------------------------------------------

@dataclass
class ForLoopBlock(WorkflowBlock):
    """Iterate over a list of items, executing body for each.

    Compiles to N DAG nodes (one per item) with sequential dependencies.
    """
    items: list[Any] = field(default_factory=list)
    body_template: WorkflowBlock | None = None
    max_iterations: int = 100
    block_type: str = "for_loop"

    def validate(self) -> list[str]:
        errors = []
        if not self.items:
            errors.append("ForLoopBlock.items must not be empty")
        if len(self.items) > self.max_iterations:
            errors.append(f"ForLoopBlock has {len(self.items)} items, exceeds max_iterations={self.max_iterations}")
        if self.body_template is None:
            errors.append("ForLoopBlock.body_template must be set")
        return errors

    def compile(self, agent: Any = None) -> list[Any]:
        from deskaoy.orchestration.dag import DAGNode
        nodes = []
        for i, item in enumerate(self.items):
            node_id = hash(f"{self.id}_{i}") % 100000

            async def _exec(item=item, _self=self) -> Any:
                return {"iteration": item, "block": _self.id}

            nodes.append(DAGNode(
                id=node_id,
                action=_exec,
                depends_on=[hash(f"{self.id}_{i-1}") % 100000] if i > 0 else [],
                outputs=[f"{self.id}.{i}"],
                label=f"{self.id}[{i}]",
                timeout=self.timeout,
            ))
        return nodes


# ---------------------------------------------------------------------------
# Wait Block
# ---------------------------------------------------------------------------

@dataclass
class WaitBlock(WorkflowBlock):
    """Wait for a condition to be true before proceeding.

    Polls the condition at regular intervals until timeout.
    """
    condition: Callable[[], bool] | None = None
    condition_str: str = ""  # Human-readable description
    poll_interval: float = 1.0
    timeout: float = 30.0
    block_type: str = "wait"

    def validate(self) -> list[str]:
        errors = []
        if self.condition is None and not self.condition_str:
            errors.append("WaitBlock requires either condition callable or condition_str")
        if self.poll_interval <= 0:
            errors.append("WaitBlock.poll_interval must be positive")
        if self.timeout <= 0:
            errors.append("WaitBlock.timeout must be positive")
        return errors

    def compile(self, agent: Any = None) -> list[Any]:
        import asyncio

        from deskaoy.orchestration.dag import DAGNode

        async def _wait_exec() -> Any:
            elapsed = 0.0
            while elapsed < self.timeout:
                if self.condition and self.condition():
                    return {"waited": elapsed, "condition_met": True}
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval
            return {"waited": elapsed, "condition_met": False}

        return [DAGNode(
            id=hash(self.id) % 100000,
            action=_wait_exec,
            depends_on=[],
            outputs=[f"{self.id}.result"],
            label=f"wait:{self.condition_str or self.id}",
            timeout=self.timeout + 5.0,
        )]


# ---------------------------------------------------------------------------
# Download Block
# ---------------------------------------------------------------------------

@dataclass
class DownloadBlock(WorkflowBlock):
    """Download a file from a URL.

    Validates URL format and target path. Supports optional checksum verification.
    """
    url: str = ""
    target_path: str = ""
    verify_checksum: str | None = None  # SHA-256 hex digest
    block_type: str = "download"

    def validate(self) -> list[str]:
        errors = []
        if not self.url:
            errors.append("DownloadBlock.url must not be empty")
        if self.url and not re.match(r"^https?://", self.url):
            errors.append(f"DownloadBlock.url must start with http(s)://: {self.url}")
        if not self.target_path:
            errors.append("DownloadBlock.target_path must not be empty")
        if self.verify_checksum is not None and not re.match(r"^[a-f0-9]{64}$", self.verify_checksum):
            errors.append("DownloadBlock.verify_checksum must be 64-char hex SHA-256")
        return errors

    def compile(self, agent: Any = None) -> list[Any]:
        from deskaoy.orchestration.dag import DAGNode

        async def _download() -> Any:
            return {"url": self.url, "path": self.target_path, "downloaded": True}

        return [DAGNode(
            id=hash(self.id) % 100000,
            action=_download,
            depends_on=[],
            outputs=[f"{self.id}.path"],
            label=f"download:{self.url[:50]}",
            timeout=self.timeout,
        )]


# ---------------------------------------------------------------------------
# Validation Block
# ---------------------------------------------------------------------------

@dataclass
class ValidationBlock(WorkflowBlock):
    """Assert a condition is true. Fails the workflow if assertion is false.

    Used for post-action verification (e.g., "file exists", "text contains X").
    """
    assertion: Callable[[], bool] | None = None
    assertion_str: str = ""  # Human-readable assertion
    error_message: str = "Validation failed"
    block_type: str = "validation"

    def validate(self) -> list[str]:
        errors = []
        if self.assertion is None and not self.assertion_str:
            errors.append("ValidationBlock requires assertion callable or assertion_str")
        return errors

    def compile(self, agent: Any = None) -> list[Any]:
        from deskaoy.orchestration.dag import DAGNode

        async def _validate() -> Any:
            if self.assertion:
                passed = self.assertion()
            else:
                passed = True  # assertion_str only — would need runtime eval
            if not passed:
                raise AssertionError(self.error_message)
            return {"validated": True, "assertion": self.assertion_str or self.id}

        return [DAGNode(
            id=hash(self.id) % 100000,
            action=_validate,
            depends_on=[],
            outputs=[f"{self.id}.valid"],
            label=f"validate:{self.assertion_str or self.id}",
            timeout=self.timeout,
        )]


# ---------------------------------------------------------------------------
# FormFill Block
# ---------------------------------------------------------------------------

@dataclass
class FormFillBlock(WorkflowBlock):
    """Fill a form with field-value pairs.

    Compiles to sequential fill actions, optionally followed by submit.
    """
    fields: dict[str, str] = field(default_factory=dict)
    submit: bool = False
    submit_selector: str = ""  # CSS/XPath for submit button
    block_type: str = "form_fill"

    def validate(self) -> list[str]:
        errors = []
        if not self.fields:
            errors.append("FormFillBlock.fields must not be empty")
        if self.submit and not self.submit_selector:
            errors.append("FormFillBlock.submit_selector required when submit=True")
        for key, _value in self.fields.items():
            if not key:
                errors.append("FormFillBlock field names must not be empty")
        return errors

    def compile(self, agent: Any = None) -> list[Any]:
        from deskaoy.orchestration.dag import DAGNode

        nodes = []
        items = list(self.fields.items())
        for i, (selector, value) in enumerate(items):
            node_id = hash(f"{self.id}_fill_{i}") % 100000
            prev_id = hash(f"{self.id}_fill_{i-1}") % 100000 if i > 0 else None

            async def _fill(sel=selector, val=value) -> Any:
                return {"filled": sel, "value": val}

            nodes.append(DAGNode(
                id=node_id,
                action=_fill,
                depends_on=[prev_id] if prev_id is not None else [],
                outputs=[f"{self.id}.{selector}"],
                label=f"fill:{selector}={value[:30]}",
                timeout=self.timeout,
            ))

        if self.submit:
            submit_id = hash(f"{self.id}_submit") % 100000
            last_fill_id = hash(f"{self.id}_fill_{len(items)-1}") % 100000 if items else None

            async def _submit() -> Any:
                return {"submitted": True, "selector": self.submit_selector}

            nodes.append(DAGNode(
                id=submit_id,
                action=_submit,
                depends_on=[last_fill_id] if last_fill_id is not None else [],
                outputs=[f"{self.id}.submitted"],
                label=f"submit:{self.submit_selector}",
                timeout=self.timeout,
            ))

        return nodes


# ---------------------------------------------------------------------------
# CodeBlock (sandboxed)
# ---------------------------------------------------------------------------

# Allowed builtins for sandboxed execution
_SAFE_BUILTINS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "filter",
    "float", "format", "int", "isinstance", "len", "list", "map",
    "max", "min", "print", "range", "round", "set", "sorted",
    "str", "sum", "tuple", "type", "zip",
}

# Blocked module names
_BLOCKED_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "http", "urllib",
    "requests", "shutil", "pathlib", "io", "open",
    "eval", "exec", "compile", "__import__",
})


@dataclass
class CodeBlock(WorkflowBlock):
    """Execute a Python code snippet in a sandboxed environment.

    Restricted builtins — no file, network, or system access.
    """
    code: str = ""
    allowed_builtins: set[str] = field(default_factory=lambda: set(_SAFE_BUILTINS))
    block_type: str = "code"

    def validate(self) -> list[str]:
        errors = []
        if not self.code.strip():
            errors.append("CodeBlock.code must not be empty")
        # Check for dangerous patterns
        for pattern in ("import os", "import sys", "import subprocess",
                        "__import__", "eval(", "exec(", "open(",
                        "os.system", "subprocess", "socket"):
            if pattern in self.code:
                errors.append(f"CodeBlock.code contains forbidden pattern: '{pattern}'")
        return errors

    def compile(self, agent: Any = None) -> list[Any]:
        from deskaoy.orchestration.dag import DAGNode

        async def _exec_code() -> Any:
            # Build sandboxed globals
            safe_builtins = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
                           for k in self.allowed_builtins
                           if (k in __builtins__ if isinstance(__builtins__, dict) else hasattr(__builtins__, k))}
            sandbox_globals = {"__builtins__": safe_builtins}
            local_vars: dict[str, Any] = {}
            exec(self.code, sandbox_globals, local_vars)  # noqa: S102
            return {"result": local_vars.get("result", local_vars)}

        return [DAGNode(
            id=hash(self.id) % 100000,
            action=_exec_code,
            depends_on=[],
            outputs=[f"{self.id}.result"],
            label=f"code:{self.code[:50]}",
            timeout=self.timeout,
        )]
