"""
IC4 PyQt6 Dialogs
Translated from C++ qt6-dialogs implementation originally for PySide6

This module provides PyQt6-based dialog widgets for IC4:
- PropertyDialog: View and edit device properties
- DeviceSelectionDialog: Select and open camera devices

Original C++ source: ic4-examples/cpp/qt6/common/qt6-dialogs/
"""

# Re-export the main dialog classes from the dialogs subpackage
from .dialogs.property_dialog import PropertyDialog
from .dialogs.device_selection_dialog import DeviceSelectionDialog

__all__ = ["PropertyDialog", "DeviceSelectionDialog"]
