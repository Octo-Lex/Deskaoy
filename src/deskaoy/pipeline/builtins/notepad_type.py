"""Built-in pipeline: type text in Windows Notepad."""

from deskaoy.pipeline.types import PipelineArg, PipelineDefinition, PipelineStep

NOTEPAD_TYPE = PipelineDefinition(
    name="notepad_type",
    description="Type text in Windows Notepad",
    surface_type="windows",
    args=[
        PipelineArg("text", str, required=True),
    ],
    steps=[
        PipelineStep("click", {"target": "Text Editor"}),
        PipelineStep("type_text", {"text": "${args.text}"}),
    ],
)
