"""Tests for App Guide Registry (BATCH-11)."""
from __future__ import annotations

import json
import os
import tempfile
import pytest

from deskaoy.guides import AppGuide, GuideRegistry


class TestAppGuide:
    def test_from_json(self):
        data = {
            "name": "TestApp",
            "process_names": ["test.exe"],
            "selectors": {"button": "auto:123"},
            "workflows": {"click_btn": [{"action": "click", "target": "auto:123"}]},
            "safety_notes": ["Be careful"],
            "tips": ["Use keyboard"],
        }
        guide = AppGuide.from_json(data)
        assert guide.name == "TestApp"
        assert guide.process_names == ["test.exe"]

    def test_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"name": "FileApp", "process_names": ["file.exe"]}, f)
            f.flush()
            guide = AppGuide.from_file(f.name)
            assert guide.name == "FileApp"
        os.unlink(f.name)

    def test_get_selector(self):
        guide = AppGuide(name="test", selectors={"button": "auto:1"})
        assert guide.get_selector("button") == "auto:1"
        assert guide.get_selector("unknown") == ""

    def test_get_workflow(self):
        guide = AppGuide(name="test", workflows={"save": [{"action": "key_press"}]})
        steps = guide.get_workflow("save")
        assert len(steps) == 1
        assert guide.get_workflow("unknown") == []


class TestGuideRegistry:
    def test_load_from_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.json"), "w") as f:
                json.dump({"name": "MyApp", "process_names": ["myapp.exe"]}, f)

            registry = GuideRegistry(tmpdir)
            guide = registry.get("MyApp")
            assert guide is not None
            assert guide.name == "MyApp"

    def test_lookup_by_process_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.json"), "w") as f:
                json.dump({"name": "MyApp", "process_names": ["myapp.exe"]}, f)

            registry = GuideRegistry(tmpdir)
            guide = registry.get("myapp.exe")
            assert guide is not None
            assert guide.name == "MyApp"

    def test_list_guides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["app1", "app2", "app3"]:
                with open(os.path.join(tmpdir, f"{name}.json"), "w") as f:
                    json.dump({"name": name, "process_names": [f"{name}.exe"]}, f)

            registry = GuideRegistry(tmpdir)
            guides = registry.list_guides()
            assert len(guides) == 3
            assert "app1" in guides

    def test_has_guide(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.json"), "w") as f:
                json.dump({"name": "TestApp", "process_names": []}, f)

            registry = GuideRegistry(tmpdir)
            assert registry.has_guide("TestApp") is True
            assert registry.has_guide("Unknown") is False

    def test_register_programmatic(self):
        registry = GuideRegistry()
        guide = AppGuide(name="Custom", process_names=["custom.exe"])
        registry.register(guide)
        assert registry.get("Custom") is not None
        assert registry.get("custom.exe") is not None

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = GuideRegistry(tmpdir)
            assert registry.list_guides() == []
            assert registry.get("anything") is None

    def test_builtin_guides_load(self):
        """Verify built-in guides directory has files."""
        from deskaoy.guides import _BUILTIN_DIR
        guides_dir = _BUILTIN_DIR / "guides"
        if guides_dir.exists():
            json_files = list(guides_dir.glob("*.json"))
            assert len(json_files) >= 3, f"Expected 3+ built-in guides, found {len(json_files)}"

            registry = GuideRegistry(guides_dir)
            assert registry.has_guide("Notepad")
            assert registry.has_guide("Calculator")
