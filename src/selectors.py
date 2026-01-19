"""Centralized selectors and locator helpers for Bravida Cloud UI."""

DIALOG_ROLE = "dialog"
FORCE_BUTTON_TEXT = "Force"
OK_BUTTON_TEXT = "OK"
CANCEL_BUTTON_TEXT = "Cancel"
FORCE_TOGGLE_SELECTOR = "button.toggleButton[aria-pressed='false']"
UNFORCE_BUTTON_TEXT = "Unforce"

INPUT_SELECTORS = [
    "input.property-dual-text",
    "input[type='number']",
    "input[type='text']",
]

EDIT_PROPERTIES_TEXT = "Edit properties"
