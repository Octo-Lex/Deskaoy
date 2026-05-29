"""Tests for Evaluation Framework (BATCH-10)."""
from __future__ import annotations

import json
import os
import tempfile
import pytest

from deskaoy.evaluation import (
    TaskDefinition,
    TaskResult,
    BenchmarkResult,
    EvalResult,
    TaskDifficulty,
    Evaluator,
    BenchmarkRunner,
)


class TestTaskDefinition:
    def test_from_json(self):
        data = {
            "id": "test-001",
            "instruction": "Open Notepad",
            "category": "text_editing",
            "difficulty": "easy",
            "evaluator": {"type": "always_pass"},
        }
        task = TaskDefinition.from_json(data)
        assert task.id == "test-001"
        assert task.instruction == "Open Notepad"
        assert task.difficulty == TaskDifficulty.EASY

    def test_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"id": "file-test", "instruction": "test"}, f)
            f.flush()
            task = TaskDefinition.from_file(f.name)
            assert task.id == "file-test"
        os.unlink(f.name)

    def test_defaults(self):
        task = TaskDefinition(id="x", instruction="y")
        assert task.platform == "windows"
        assert task.max_steps == 15
        assert task.tags == []


class TestEvaluator:
    def test_exact_match_pass(self):
        result = Evaluator.evaluate({"type": "exact_match", "expected": "hello"}, "hello")
        assert result.result == EvalResult.PASS
        assert result.score == 1.0

    def test_exact_match_fail(self):
        result = Evaluator.evaluate({"type": "exact_match", "expected": "hello"}, "world")
        assert result.result == EvalResult.FAIL

    def test_contains_pass(self):
        result = Evaluator.evaluate({"type": "contains", "content": "hello"}, "say hello world")
        assert result.result == EvalResult.PASS

    def test_contains_fail(self):
        result = Evaluator.evaluate({"type": "contains", "content": "xyz"}, "hello world")
        assert result.result == EvalResult.FAIL

    def test_file_exists_pass(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test")
            f.flush()
            result = Evaluator.evaluate({"type": "file_exists", "path": f.name}, None)
            assert result.result == EvalResult.PASS
        os.unlink(f.name)

    def test_file_exists_fail(self):
        result = Evaluator.evaluate({"type": "file_exists", "path": "/nonexistent/file.txt"}, None)
        assert result.result == EvalResult.FAIL

    def test_file_contains_pass(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello World\nLine 2")
            f.flush()
            result = Evaluator.evaluate({"type": "file_contains", "path": f.name, "content": "Hello"}, None)
            assert result.result == EvalResult.PASS
        os.unlink(f.name)

    def test_file_contains_fail(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello World")
            f.flush()
            result = Evaluator.evaluate({"type": "file_contains", "path": f.name, "content": "xyz"}, None)
            assert result.result == EvalResult.FAIL
        os.unlink(f.name)

    def test_always_pass(self):
        result = Evaluator.evaluate({"type": "always_pass"}, None)
        assert result.result == EvalResult.PASS

    def test_always_fail(self):
        result = Evaluator.evaluate({"type": "always_fail"}, None)
        assert result.result == EvalResult.FAIL

    def test_unknown_evaluator(self):
        result = Evaluator.evaluate({"type": "nonexistent"}, None)
        assert result.result == EvalResult.ERROR
        assert "Unknown" in result.error


class TestBenchmarkRunner:
    def test_run_single_task(self):
        task = TaskDefinition(
            id="t1", instruction="test", evaluator={"type": "always_pass"},
        )
        runner = BenchmarkRunner("test")
        result = runner.run_task(task)
        assert result.passed

    def test_run_multiple_tasks(self):
        tasks = [
            TaskDefinition(id="t1", instruction="pass", evaluator={"type": "always_pass"}),
            TaskDefinition(id="t2", instruction="fail", evaluator={"type": "always_fail"}),
        ]
        runner = BenchmarkRunner("test")
        result = runner.run_tasks(tasks)
        assert result.tasks_total == 2
        assert result.tasks_passed == 1
        assert result.tasks_failed == 1
        assert result.overall_score == 0.5

    def test_pass_rate(self):
        tasks = [
            TaskDefinition(id="t1", instruction="a", evaluator={"type": "always_pass"}),
            TaskDefinition(id="t2", instruction="b", evaluator={"type": "always_pass"}),
            TaskDefinition(id="t3", instruction="c", evaluator={"type": "always_pass"}),
        ]
        runner = BenchmarkRunner("test")
        result = runner.run_tasks(tasks)
        assert result.pass_rate == 1.0

    def test_format_results(self):
        tasks = [
            TaskDefinition(id="t1", instruction="pass", evaluator={"type": "always_pass"}),
        ]
        runner = BenchmarkRunner("test")
        result = runner.run_tasks(tasks)
        text = BenchmarkRunner.format_results(result)
        assert "test" in text
        assert "PASS" in text

    def test_empty_benchmark(self):
        runner = BenchmarkRunner("empty")
        result = runner.run_tasks([])
        assert result.pass_rate == 0.0
        assert result.tasks_total == 0

    def test_run_from_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                path = os.path.join(tmpdir, f"task-{i}.json")
                with open(path, "w") as f:
                    json.dump({
                        "id": f"t{i}",
                        "instruction": f"task {i}",
                        "evaluator": {"type": "always_pass"},
                    }, f)

            runner = BenchmarkRunner("dir-test")
            result = runner.run_from_directory(tmpdir)
            assert result.tasks_total == 3
            assert result.tasks_passed == 3

    def test_sample_tasks_load(self):
        """Verify sample task files in tasks/ directory load correctly."""
        tasks_dir = os.path.join(os.path.dirname(__file__), "..", "..", "tasks")
        if not os.path.exists(tasks_dir):
            pytest.skip("No tasks/ directory")

        json_files = [f for f in os.listdir(tasks_dir) if f.endswith(".json")]
        assert len(json_files) >= 10, f"Expected 10+ task files, found {len(json_files)}"

        for fname in json_files:
            path = os.path.join(tasks_dir, fname)
            task = TaskDefinition.from_file(path)
            assert task.id, f"Task in {fname} missing id"
            assert task.instruction, f"Task in {fname} missing instruction"
