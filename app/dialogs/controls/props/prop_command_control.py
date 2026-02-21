"""
Command property control
Translated from C++ PropCommandControl.h
"""

from PyQt6.QtWidgets import QPushButton, QMessageBox, QWidget
from typing import Optional

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropCommand
from .prop_control_base import PropControlBase


class PropCommandControl(PropControlBase):
    """Control widget for command properties"""

    prop: PropCommand

    def __init__(
        self, prop: PropCommand, parent: Optional[QWidget], grabber: Optional[Grabber]
    ):
        super().__init__(prop, parent, grabber)

        text = self.prop.display_name

        self.button = QPushButton(text, self)
        self.button.clicked.connect(self._on_execute)

        self.update_all()

        if layout := self.layout():
            layout.addWidget(self.button)

    def _on_execute(self):
        """Execute the command (matches C++ execute)"""

        def execute_func():
            self.prop.execute()

        if not self.prop_execute(execute_func):
            QMessageBox.critical(self, "", "Failed to execute command")
        else:
            try:
                if not self.prop.is_done:
                    self.button.setEnabled(False)
            except Exception:
                pass

    def update_all(self):
        """Update button state"""
        try:
            is_done = self.prop.is_done
            is_locked = self.should_display_as_locked()

            self.button.setEnabled(not is_locked and is_done)
        except Exception:
            self.button.setEnabled(False)
