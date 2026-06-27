"""Evaluation Framework — OSWorld-compatible task scoring.

Defines the task format, evaluators, and benchmark runner for measuring
DesktopAgent performance on real-world desktop automation tasks.

Task Format (JSON):
  {
    "id": "win-001",
    "instruction": "Open Notepad and type Hello World",
    "category": "text_editing",
    "difficulty": "easy",
    "platform": "windows",
    "setup": [],
    "evaluator": {"type": "file_contains", "path": "...", "content": "Hello World"},
    "max_steps": 10,
    "timeout_seconds": 60
  }

Built-in Evaluators:
  - exact_match: result must match expected string exactly
  - contains: result must contain expected substring
  - file_exists: file must exist at given path
  - file_contains: file must contain expected content
  - screenshot_diff: screenshot must differ from baseline by < threshold
  - process_running: process must be running
  - window_title: window with given title must exist
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class TaskDifficulty(StrEnum):
    TRIVIAL = "trivial"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class EvalResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"
    TIMEOUT = "timeout"


@dataclass
class TaskDefinition:
    """A single evaluation task."""
    id: str
    instruction: str
    category: str = ""
    difficulty: TaskDifficulty = TaskDifficulty.EASY
    platform: str = "windows"
    setup: list[dict] = field(default_factory=list)
    evaluator: dict = field(default_factory=dict)
    max_steps: int = 15
    timeout_seconds: float = 120.0
    tags: list[str] = field(default_factory=list)

    @staticmethod
    def from_json(data: dict) -> TaskDefinition:
        """Parse from JSON dict."""
        diff = data.get("difficulty", "easy")
        if isinstance(diff, str):
            diff = TaskDifficulty(diff)
        return TaskDefinition(
            id=data.get("id", "unknown"),
            instruction=data.get("instruction", ""),
            category=data.get("category", ""),
            difficulty=diff,
            platform=data.get("platform", "windows"),
            setup=data.get("setup", []),
            evaluator=data.get("evaluator", {}),
            max_steps=data.get("max_steps", 15),
            timeout_seconds=data.get("timeout_seconds", 120.0),
            tags=data.get("tags", []),
        )

    @staticmethod
    def from_file(path: str | Path) -> TaskDefinition:
        """Load from a JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return TaskDefinition.from_json(data)


@dataclass
class TaskResult:
    """Result of evaluating a single task."""
    task_id: str
    result: EvalResult
    score: float = 0.0  # 0.0–1.0
    steps_used: int = 0
    duration_seconds: float = 0.0
    evidence: str = ""
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.result == EvalResult.PASS


@dataclass
class BenchmarkResult:
    """Result of running a full benchmark suite."""
    name: str
    tasks_total: int
    tasks_passed: int
    tasks_failed: int
    tasks_error: int
    results: list[TaskResult] = field(default_factory=list)
    duration_seconds: float = 0.0
    overall_score: float = 0.0

    @property
    def pass_rate(self) -> float:
        if self.tasks_total == 0:
            return 0.0
        return self.tasks_passed / self.tasks_total


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------

class Evaluator:
    """Built-in task evaluators."""

    @staticmethod
    def evaluate(eval_config: dict, execution_result: Any = None) -> TaskResult:
        """Run the appropriate evaluator based on config type."""
        eval_type = eval_config.get("type", "")

        evaluators: dict[str, Callable] = {
            "exact_match": Evaluator._eval_exact_match,
            "contains": Evaluator._eval_contains,
            "file_exists": Evaluator._eval_file_exists,
            "file_contains": Evaluator._eval_file_contains,
            "process_running": Evaluator._eval_process_running,
            "window_title": Evaluator._eval_window_title,
            "always_pass": Evaluator._eval_always_pass,
            "always_fail": Evaluator._eval_always_fail,
        }

        evaluator_fn = evaluators.get(eval_type)
        if evaluator_fn is None:
            return TaskResult(
                task_id="",
                result=EvalResult.ERROR,
                error=f"Unknown evaluator type: {eval_type}",
            )

        return evaluator_fn(eval_config, execution_result)

    @staticmethod
    def _eval_exact_match(config: dict, result: Any) -> TaskResult:
        expected = config.get("expected", "")
        actual = str(result) if result is not None else ""
        passed = actual == expected
        return TaskResult(
            task_id="",
            result=EvalResult.PASS if passed else EvalResult.FAIL,
            score=1.0 if passed else 0.0,
            evidence=f"expected={expected!r}, actual={actual!r}",
        )

    @staticmethod
    def _eval_contains(config: dict, result: Any) -> TaskResult:
        expected = config.get("content", config.get("expected", ""))
        actual = str(result) if result is not None else ""
        passed = expected in actual
        return TaskResult(
            task_id="",
            result=EvalResult.PASS if passed else EvalResult.FAIL,
            score=1.0 if passed else 0.0,
            evidence=f"looking for {expected!r} in output ({len(actual)} chars)",
        )

    @staticmethod
    def _eval_file_exists(config: dict, result: Any) -> TaskResult:
        path = config.get("path", "")
        exists = os.path.exists(path)
        return TaskResult(
            task_id="",
            result=EvalResult.PASS if exists else EvalResult.FAIL,
            score=1.0 if exists else 0.0,
            evidence=f"file {path!r} {'exists' if exists else 'not found'}",
        )

    @staticmethod
    def _eval_file_contains(config: dict, result: Any) -> TaskResult:
        path = config.get("path", "")
        content = config.get("content", "")
        case_insensitive = config.get("case_insensitive", False)

        if not os.path.exists(path):
            return TaskResult(
                task_id="",
                result=EvalResult.FAIL,
                score=0.0,
                evidence=f"file {path!r} not found",
            )

        try:
            file_content = Path(path).read_text(encoding="utf-8", errors="replace")
            if case_insensitive:
                passed = content.lower() in file_content.lower()
            else:
                passed = content in file_content
            return TaskResult(
                task_id="",
                result=EvalResult.PASS if passed else EvalResult.FAIL,
                score=1.0 if passed else 0.0,
                evidence=f"looking for {content!r} in {path} ({len(file_content)} chars)",
            )
        except Exception as exc:
            return TaskResult(
                task_id="",
                result=EvalResult.ERROR,
                error=str(exc),
            )

    @staticmethod
    def _eval_process_running(config: dict, result: Any) -> TaskResult:
        name = config.get("name", "")
        try:
            import subprocess
            proc = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}"],
                capture_output=True, text=True, timeout=5,
            )
            running = name.lower() in proc.stdout.lower()
        except Exception:
            running = False

        return TaskResult(
            task_id="",
            result=EvalResult.PASS if running else EvalResult.FAIL,
            score=1.0 if running else 0.0,
            evidence=f"process {name!r} {'running' if running else 'not found'}",
        )

    @staticmethod
    def _eval_window_title(config: dict, result: Any) -> TaskResult:
        config.get("title", "")
        # Stub — would need win32gui in production
        return TaskResult(
            task_id="",
            result=EvalResult.SKIP,
            score=0.0,
            evidence="window_title evaluator skipped (no adapter)",
        )

    @staticmethod
    def _eval_always_pass(config: dict, result: Any) -> TaskResult:
        return TaskResult(task_id="", result=EvalResult.PASS, score=1.0, evidence="always_pass")

    @staticmethod
    def _eval_always_fail(config: dict, result: Any) -> TaskResult:
        return TaskResult(task_id="", result=EvalResult.FAIL, score=0.0, evidence="always_fail")


# ---------------------------------------------------------------------------
# Benchmark Runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    """Run a suite of evaluation tasks and produce a benchmark result.

    Usage::

        runner = BenchmarkRunner("windows-basic")
        result = runner.run_from_directory("tasks/")
        print(f"Pass rate: {result.pass_rate:.1%}")
    """

    def __init__(self, name: str = "benchmark") -> None:
        self.name = name

    def run_task(self, task: TaskDefinition, agent: Any = None) -> TaskResult:
        """Run a single task and evaluate it."""
        start = time.monotonic()

        try:
            # In production: agent executes the instruction
            # For now: skip execution, just evaluate
            execution_result = None

            if agent:
                # Future: call agent.execute(instruction)
                pass

            # Evaluate
            result = Evaluator.evaluate(task.evaluator, execution_result)
            result.task_id = task.id
            result.duration_seconds = time.monotonic() - start
            return result

        except Exception as exc:
            return TaskResult(
                task_id=task.id,
                result=EvalResult.ERROR,
                duration_seconds=time.monotonic() - start,
                error=str(exc),
            )

    def run_tasks(self, tasks: list[TaskDefinition], agent: Any = None) -> BenchmarkResult:
        """Run a list of tasks and produce a benchmark result."""
        start = time.monotonic()
        results: list[TaskResult] = []

        for task in tasks:
            result = self.run_task(task, agent)
            results.append(result)

        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if r.result == EvalResult.FAIL)
        errored = sum(1 for r in results if r.result in (EvalResult.ERROR, EvalResult.TIMEOUT))

        return BenchmarkResult(
            name=self.name,
            tasks_total=len(tasks),
            tasks_passed=passed,
            tasks_failed=failed,
            tasks_error=errored,
            results=results,
            duration_seconds=time.monotonic() - start,
            overall_score=passed / len(tasks) if tasks else 0.0,
        )

    def run_from_directory(self, directory: str | Path, agent: Any = None) -> BenchmarkResult:
        """Load all JSON task files from a directory and run them."""
        dir_path = Path(directory)
        tasks: list[TaskDefinition] = []

        for json_file in sorted(dir_path.glob("*.json")):
            try:
                task = TaskDefinition.from_file(json_file)
                tasks.append(task)
            except Exception as exc:
                logger.warning("Failed to load task %s: %s", json_file, exc)

        return self.run_tasks(tasks, agent)

    @staticmethod
    def format_results(result: BenchmarkResult) -> str:
        """Format benchmark results as a readable table."""
        lines = [
            f"Benchmark: {result.name}",
            f"{'='*50}",
            f"Total: {result.tasks_total}  |  Passed: {result.tasks_passed}  |  Failed: {result.tasks_failed}  |  Error: {result.tasks_error}",
            f"Overall Score: {result.overall_score:.1%}",
            f"Duration: {result.duration_seconds:.1f}s",
            f"{'-'*50}",
        ]

        for r in result.results:
            icon = "PASS" if r.passed else r.result.value.upper()
            lines.append(f"  [{icon:>7}] {r.task_id:20s} score={r.score:.0%}  {r.evidence}")

        return "\n".join(lines)
