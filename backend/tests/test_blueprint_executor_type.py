"""Tests for Phase 5: Blueprint executor_type field and fork mechanism."""

from __future__ import annotations

from deerflow.report_templates.blueprint_schema import BlueprintDefinition


class TestBlueprintExecutorType:
    """Test executor_type field in BlueprintDefinition."""

    def test_blueprint_definition_has_executor_type_field(self):
        """Test that BlueprintDefinition includes executor_type field."""
        assert hasattr(BlueprintDefinition, "model_fields")
        assert "executor_type" in BlueprintDefinition.model_fields

    def test_blueprint_definition_executor_type_default_is_direct(self):
        """Test that executor_type defaults to 'direct'."""
        field = BlueprintDefinition.model_fields["executor_type"]
        assert field.default == "direct"

    def test_blueprint_definition_executor_type_accepts_dsl(self):
        """Test that executor_type accepts 'dsl' value."""
        # Use an existing blueprint for testing
        from deerflow.report_templates.blueprint_generator import generate_blueprint

        blueprint = generate_blueprint("daily-equipment")
        blueprint.executor_type = "dsl"

        assert blueprint.executor_type == "dsl"

    def test_blueprint_definition_executor_type_accepts_direct(self):
        """Test that executor_type accepts 'direct' value."""
        # Use an existing blueprint for testing
        from deerflow.report_templates.blueprint_generator import generate_blueprint

        blueprint = generate_blueprint("daily-equipment")
        blueprint.executor_type = "direct"

        assert blueprint.executor_type == "direct"


class TestBlueprintGenerator:
    """Test blueprint_generator.py sets executor_type correctly."""

    def test_generate_blueprint_sets_executor_type_direct(self):
        """Test that generate_blueprint sets executor_type='direct' for builtin templates."""
        from deerflow.report_templates.blueprint_generator import generate_blueprint

        blueprint = generate_blueprint("daily-equipment")
        assert blueprint.executor_type == "direct"

    def test_generate_all_blueprints_all_have_executor_type_direct(self):
        """Test that all generated blueprints have executor_type='direct'."""
        from deerflow.report_templates.blueprint_generator import generate_all_blueprints

        blueprints = generate_all_blueprints()
        assert len(blueprints) > 0

        for blueprint in blueprints:
            assert blueprint.executor_type == "direct", f"Blueprint {blueprint.id} should have executor_type='direct'"
