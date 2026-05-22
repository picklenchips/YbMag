"""
Category property control
Translated from C++ PropCategoryControl.h
"""

from typing import Optional

from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget

from imagingcontrol4.properties import PropCategory
from .prop_control_base import PropControlBase


class PropCategoryControl(PropControlBase):
    """Control widget for category properties"""

    prop: PropCategory

    def __init__(self, prop: PropCategory, parent: Optional[QWidget]):
        super().__init__(prop, parent, None)

        # Match C++ CustomStyle.PropCategoryControlStyle
        self.setStyleSheet("QWidget { background-color: palette(mid); }")

        label = QLabel(self)
        # Match C++ CustomStyle.PropCategoryControlLabelStyle
        label.setStyleSheet("QWidget { background-color: palette(mid); }")
        label.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding
        )

        if layout := self.layout():
            layout.addWidget(label)
            layout.setContentsMargins(0, 4, 0, 4)

    def update_all(self):
        """No updates required for category control"""
        return
