import os
import pytest

from sight_core.ui_grounding import (
    UIGroundingService,
    UIControl,
    UIControlType,
    classify_control_class,
)
from sight_core.vision import BoundingBox


def test_classify_control_class():
    assert classify_control_class("Button") == UIControlType.BUTTON
    assert classify_control_class("WPF_Button_Custom") == UIControlType.BUTTON
    assert classify_control_class("Edit") == UIControlType.EDIT
    assert classify_control_class("RichEdit20W") == UIControlType.EDIT
    assert classify_control_class("Static") == UIControlType.LABEL
    assert classify_control_class("ComboBox") == UIControlType.COMBOBOX
    assert classify_control_class("CustomDialogClass") == UIControlType.WINDOW
    assert classify_control_class("UnknownWidget") == UIControlType.GENERIC


def test_grounding_coordinate_mock():
    service = UIGroundingService()
    # Mock enumerate_controls
    mock_controls = [
        UIControl(
            hwnd=101,
            class_name="Dialog",
            control_type=UIControlType.WINDOW,
            text="App Window",
            bounding_box=BoundingBox(left=100, top=100, width=500, height=400),
            is_enabled=True,
            is_visible=True,
        ),
        UIControl(
            hwnd=102,
            class_name="Button",
            control_type=UIControlType.BUTTON,
            text="Save File",
            bounding_box=BoundingBox(left=150, top=150, width=120, height=35),
            is_enabled=True,
            is_visible=True,
        ),
    ]
    service.enumerate_controls = lambda parent_hwnd=None: mock_controls

    # Coordinate inside the button (160, 160)
    hit = service.ground_coordinate(160, 160)
    assert hit is not None
    assert hit.hwnd == 102
    assert hit.control_type == UIControlType.BUTTON
    assert hit.text == "Save File"

    # Coordinate outside the button but inside the window (200, 300)
    hit_win = service.ground_coordinate(200, 300)
    assert hit_win is not None
    assert hit_win.hwnd == 101

    # Coordinate completely outside (50, 50)
    hit_none = service.ground_coordinate(50, 50)
    assert hit_none is None


def test_find_control_by_text_mock():
    service = UIGroundingService()
    mock_controls = [
        UIControl(
            hwnd=201,
            class_name="Button",
            control_type=UIControlType.BUTTON,
            text="Submit Form",
            bounding_box=BoundingBox(left=50, top=50, width=100, height=30),
            is_enabled=True,
            is_visible=True,
        ),
    ]
    service.enumerate_controls = lambda parent_hwnd=None: mock_controls

    found = service.find_control_by_text("submit")
    assert found is not None
    assert found.hwnd == 201

    not_found = service.find_control_by_text("cancel")
    assert not_found is None
