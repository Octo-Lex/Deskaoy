"""Tests for Templates — pre-built orchestration patterns."""

from deskaoy.orchestration.templates import match_template, list_templates, TEMPLATES


class TestMatchTemplate:
    def test_email_to_task_match(self):
        result = match_template("Read email and create a task in Notion")
        assert result is not None
        assert "email_to_task" in TEMPLATES
        assert len(result["subtasks"]) == 2

    def test_screenshot_to_note_match(self):
        result = match_template("Take a screenshot and save as a note")
        assert result is not None
        assert len(result["subtasks"]) == 2

    def test_copy_paste_match(self):
        result = match_template("Copy text from source and paste to destination")
        assert result is not None
        assert len(result["subtasks"]) == 2

    def test_no_match_returns_none(self):
        result = match_template("Calculate fibonacci sequence")
        assert result is None

    def test_partial_match(self):
        """At least 50% of trigger words must match."""
        # "email" alone should match email_to_task (1/3 words ≈ 33%, below threshold)
        # "email task" should match (2/3 words ≈ 67%, above threshold)
        result = match_template("Create an email task")
        assert result is not None

    def test_case_insensitive(self):
        result = match_template("READ EMAIL AND CREATE A TASK")
        assert result is not None

    def test_template_has_description(self):
        for name, template in TEMPLATES.items():
            assert "description" in template
            assert "trigger" in template
            assert "subtasks" in template
            assert len(template["subtasks"]) > 0

    def test_template_subtasks_have_required_fields(self):
        for name, template in TEMPLATES.items():
            for st in template["subtasks"]:
                assert "id" in st
                assert "app" in st
                assert "instruction" in st


class TestListTemplates:
    def test_returns_list(self):
        templates = list_templates()
        assert isinstance(templates, list)
        assert len(templates) >= 3

    def test_entry_fields(self):
        templates = list_templates()
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert "trigger_keywords" in t
            assert "subtask_count" in t
            assert t["subtask_count"] > 0
