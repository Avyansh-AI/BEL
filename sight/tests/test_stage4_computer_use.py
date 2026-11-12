"""Stage 4 Verification Tests: Advanced Computer Use."""
from sight_core.computer_use import (
    ClipboardManager,
    ComputerUseOrchestrator,
    RecordedWorkflow,
    UnexpectedDialogDetector,
    WorkflowAction,
)
from sight_core.ui_grounding import UIControl, UIControlType
from sight_core.vision import BoundingBox


def test_stage4_grounding_clipboard_and_unexpected_dialog(tmp_path):
    orch = ComputerUseOrchestrator(tmp_path)
    controls = [
        UIControl(
            hwnd=101,
            class_name="Button",
            control_type=UIControlType.BUTTON,
            text="Save Project",
            bounding_box=BoundingBox(left=10, top=20, width=80, height=30),
            is_enabled=True,
            is_visible=True,
        ),
        UIControl(
            hwnd=102,
            class_name="Dialog",
            control_type=UIControlType.WINDOW,
            text="Error: Disk Full",
            bounding_box=BoundingBox(left=0, top=0, width=300, height=200),
            is_enabled=True,
            is_visible=True,
        ),
    ]
    found = orch.find_element("save project", controls=controls[:1])
    assert found is not None and found.hwnd == 101

    cb = ClipboardManager()
    cb.set_text("BEL_CLIPBOARD_TEST")
    assert cb.get_text() == "BEL_CLIPBOARD_TEST"

    alert = UnexpectedDialogDetector().detect(controls=controls)
    assert alert is not None and "Error: Disk Full" in alert


def test_stage4_approval_recovery_and_workflow_replay(tmp_path):
    orch = ComputerUseOrchestrator(tmp_path)
    orch.register_executor("click", lambda act: {"success": False, "error": "Element moved"})
    orch.register_executor("hotkey", lambda act: {"success": True})

    # Consequential action blocked without approval
    conseq = WorkflowAction(kind="hotkey", arguments={"keys": "ctrl+s"}, is_consequential=True)
    blocked = orch.execute_action(conseq, approved=False)
    assert not blocked.success and "Approval required" in blocked.error

    # Recovery via fallback action + workflow record/replay
    wf = RecordedWorkflow(
        workflow_id="save_flow",
        name="Save Flow",
        actions=[
            WorkflowAction(
                kind="click",
                target_query="Save",
                fallback_kind="hotkey",
                fallback_arguments={"keys": "ctrl+s"},
                is_consequential=True,
            ),
            WorkflowAction(kind="file_dialog", arguments={"path": "out.txt"}),
        ],
    )
    orch.recorder.save(wf)
    assert "save_flow" in orch.recorder.list_workflows()

    reports = orch.replay_workflow("save_flow", approved_consequential=True)
    assert len(reports) == 2
    assert all(r.success and r.pre_observed and r.post_verified for r in reports)
    assert reports[0].recovered is True
