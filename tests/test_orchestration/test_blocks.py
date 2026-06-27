"""Tests for Typed Workflow Blocks + WorkflowBuilder (BATCH-07)."""
from __future__ import annotations

import asyncio

import pytest

from deskaoy.orchestration.blocks import (
    CodeBlock,
    DownloadBlock,
    ForLoopBlock,
    FormFillBlock,
    ValidationBlock,
    WaitBlock,
)
from deskaoy.orchestration.workflow import WorkflowBuilder

# ---------------------------------------------------------------------------
# Block Validation Tests
# ---------------------------------------------------------------------------

class TestForLoopBlock:
    def test_valid(self):
        # Create a concrete body_template
        body = DownloadBlock(id="body", url="https://x.com/f", target_path="/tmp/f")
        block = ForLoopBlock(id="loop", items=[1, 2, 3], body_template=body)
        assert block.validate() == []

    def test_empty_items_invalid(self):
        block = ForLoopBlock(id="loop", items=[], body_template=None)
        errors = block.validate()
        assert any("items must not be empty" in e for e in errors)

    def test_max_iterations_exceeded(self):
        block = ForLoopBlock(id="loop", items=list(range(200)), body_template=None, max_iterations=100)
        errors = block.validate()
        assert any("exceeds max_iterations" in e for e in errors)

    def test_no_body_template(self):
        block = ForLoopBlock(id="loop", items=[1], body_template=None)
        errors = block.validate()
        assert any("body_template" in e for e in errors)

    def test_compile_produces_nodes(self):
        # Use a mock body_template to avoid abstract methods
        block = ForLoopBlock(id="loop", items=["a", "b", "c"], body_template=object())
        nodes = block.compile()
        assert len(nodes) == 3
        assert nodes[0].label == "loop[0]"
        assert nodes[1].depends_on  # second depends on first


class TestWaitBlock:
    def test_valid_with_callable(self):
        block = WaitBlock(id="wait", condition=lambda: True, condition_str="Always true")
        assert block.validate() == []

    def test_invalid_no_condition(self):
        block = WaitBlock(id="wait")
        errors = block.validate()
        assert any("condition" in e for e in errors)

    def test_invalid_negative_poll(self):
        block = WaitBlock(id="wait", condition=lambda: True, poll_interval=-1)
        errors = block.validate()
        assert any("poll_interval" in e for e in errors)

    def test_compile_produces_node(self):
        block = WaitBlock(id="wait", condition=lambda: True)
        nodes = block.compile()
        assert len(nodes) == 1


class TestDownloadBlock:
    def test_valid(self):
        block = DownloadBlock(id="dl", url="https://example.com/file.zip", target_path="/tmp/file.zip")
        assert block.validate() == []

    def test_invalid_url(self):
        block = DownloadBlock(id="dl", url="not-a-url", target_path="/tmp/x")
        errors = block.validate()
        assert any("http" in e for e in errors)

    def test_empty_target(self):
        block = DownloadBlock(id="dl", url="https://example.com/f", target_path="")
        errors = block.validate()
        assert any("target_path" in e for e in errors)

    def test_invalid_checksum(self):
        block = DownloadBlock(id="dl", url="https://x.com/f", target_path="/tmp/f",
                            verify_checksum="not-hex")
        errors = block.validate()
        assert any("checksum" in e for e in errors)


class TestValidationBlock:
    def test_valid_with_callable(self):
        block = ValidationBlock(id="check", assertion=lambda: True)
        assert block.validate() == []

    def test_invalid_no_assertion(self):
        block = ValidationBlock(id="check")
        errors = block.validate()
        assert any("assertion" in e for e in errors)

    def test_compile_passes(self):
        block = ValidationBlock(id="check", assertion=lambda: True)
        nodes = block.compile()
        assert len(nodes) == 1
        result = asyncio.run(nodes[0].action())
        assert result["validated"] is True

    def test_compile_fails_raises(self):
        block = ValidationBlock(id="check", assertion=lambda: False, error_message="Failed!")
        nodes = block.compile()
        with pytest.raises(AssertionError, match="Failed!"):
            asyncio.run(nodes[0].action())


class TestFormFillBlock:
    def test_valid(self):
        block = FormFillBlock(id="form", fields={"name": "Alice"}, submit=True, submit_selector="#submit")
        assert block.validate() == []

    def test_empty_fields(self):
        block = FormFillBlock(id="form", fields={})
        errors = block.validate()
        assert any("fields" in e for e in errors)

    def test_submit_without_selector(self):
        block = FormFillBlock(id="form", fields={"x": "y"}, submit=True)
        errors = block.validate()
        assert any("submit_selector" in e for e in errors)

    def test_compile_with_submit(self):
        block = FormFillBlock(id="form", fields={"name": "Alice", "email": "a@b.com"},
                            submit=True, submit_selector="#go")
        nodes = block.compile()
        assert len(nodes) == 3  # 2 fills + 1 submit

    def test_compile_without_submit(self):
        block = FormFillBlock(id="form", fields={"name": "Alice"})
        nodes = block.compile()
        assert len(nodes) == 1


class TestCodeBlock:
    def test_valid(self):
        block = CodeBlock(id="code", code="result = 1 + 1")
        assert block.validate() == []

    def test_empty_code(self):
        block = CodeBlock(id="code", code="")
        errors = block.validate()
        assert any("empty" in e for e in errors)

    def test_forbidden_import_os(self):
        block = CodeBlock(id="code", code="import os\nresult = os.path")
        errors = block.validate()
        assert any("forbidden" in e for e in errors)

    def test_forbidden_exec(self):
        block = CodeBlock(id="code", code="exec('print(1)')")
        errors = block.validate()
        assert any("forbidden" in e for e in errors)

    def test_compile_executes(self):
        block = CodeBlock(id="code", code="result = 42")
        nodes = block.compile()
        output = asyncio.run(nodes[0].action())
        assert output["result"] == 42


# ---------------------------------------------------------------------------
# WorkflowBuilder Tests
# ---------------------------------------------------------------------------

class TestWorkflowBuilder:
    def test_fluent_api(self):
        builder = (WorkflowBuilder("test")
            .add_unsafe(DownloadBlock(id="dl", url="https://x.com/f", target_path="/tmp/f")))
        assert builder.block_count == 1

    def test_add_validates(self):
        with pytest.raises(ValueError, match="validation failed"):
            WorkflowBuilder("test").add(FormFillBlock(id="form", fields={}))

    def test_to_dag_nodes(self):
        builder = (WorkflowBuilder("test")
            .add_unsafe(DownloadBlock(id="dl1", url="https://x.com/a", target_path="/tmp/a"))
            .add_unsafe(DownloadBlock(id="dl2", url="https://x.com/b", target_path="/tmp/b")))
        nodes = builder.to_dag_nodes()
        assert len(nodes) == 2
        # Second block depends on first
        assert nodes[1].depends_on != []

    def test_describe(self):
        builder = WorkflowBuilder("my-workflow")
        builder.add_unsafe(DownloadBlock(id="dl", url="https://x.com/f", target_path="/tmp/f"))
        desc = builder.describe()
        assert "my-workflow" in desc
        assert "download" in desc

    def test_validate_all(self):
        builder = WorkflowBuilder("test")
        builder.add_unsafe(FormFillBlock(id="form", fields={}))
        errors = builder.validate_all()
        assert "form" in errors

    def test_from_blocks(self):
        blocks = [
            DownloadBlock(id="dl1", url="https://x.com/a", target_path="/tmp/a"),
            DownloadBlock(id="dl2", url="https://x.com/b", target_path="/tmp/b"),
        ]
        builder = WorkflowBuilder.from_blocks("bulk", blocks)
        assert builder.block_count == 2

    def test_empty_workflow(self):
        builder = WorkflowBuilder("empty")
        assert builder.to_dag_nodes() == []
        assert builder.block_count == 0
