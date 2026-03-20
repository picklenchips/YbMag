from PyQt6.QtCore import QTimer, pyqtSignal, QEvent, QTime
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget, QHBoxLayout, QLabel, QComboBox, QSizePolicy
from typing import Optional

from imagingcontrol4.properties import PropInteger, PropertyVisibility
from imagingcontrol4.propconstants import PropId
from imagingcontrol4.grabber import Grabber, StreamSetupOption

from .props.prop_control_base import (
    StreamRestartInfo,
    StreamRestartFilterFunction,
    MultiPropControlBase,
)


class BinningDecimationControl(MultiPropControlBase):
    """
    Single combo box for binning/decimation control. 
    Options: "None", "2x2 Binning", "2x2 Decimation".
    Sets both properties using _set_property_value.
    Both are :py:class:`imagingcontrol4.properties.PropInt` with int_value representing the current setting (1 for off, 2 for x2).
    """

    UPDATE_ALL = QEvent.Type.User + 1
    valueChanged = pyqtSignal(int, int)  # Emits (binning_value, decimation_value) on user change

    def __init__(
        self,
        grabber: Grabber,
        parent: Optional[QWidget] = None,
    ):
        self.prop_map = grabber.device_property_map
        # 0 = BV, 1 = BH, 2 = DV, 3 = DH
        props = [
            self.prop_map.find(PropId.BINNING_VERTICAL),
            self.prop_map.find(PropId.BINNING_HORIZONTAL),
            self.prop_map.find(PropId.DECIMATION_VERTICAL),
            self.prop_map.find(PropId.DECIMATION_HORIZONTAL),
        ]
        super().__init__(props, parent, grabber)

        self.combo = QComboBox(self)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.addWidget(QLabel("Binning/Decimation", self))
        layout.addWidget(self.combo)
        self.setLayout(layout)

        self.combo.addItem("None")
        self.combo.addItem("2x2 Binning")
        self.combo.addItem("2x2 Decimation")

        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.combo.installEventFilter(self)
        self.destroyed.connect(self._on_destroyed)

        self.update_all()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn:
            if watched == self.combo:
                # need to set self.prop_selected_func
                self.on_prop_selected()
        return super().eventFilter(watched, event)

    def _on_combo_changed(self, idx):
        if self._block_signals or idx < 0:
            return
        # None: set all to 1
        if idx == 0:
            for i in range(4):
                self.set_prop(i, 1)
            self.valueChanged.emit(1, 1)
        # 2x2 Binning: binning=2, decimation=1
        elif idx == 1:
            self.set_prop(2, 1)
            self.set_prop(3, 1)
            self.set_prop(0, 2)
            self.set_prop(1, 2)
            self.valueChanged.emit(2, 1)
        # 2x2 Decimation: binning=1, decimation=2
        elif idx == 2:
            self.set_prop(0, 1)
            self.set_prop(1, 1)
            self.set_prop(2, 2)
            self.set_prop(3, 2)
            self.valueChanged.emit(1, 2)
        else:
            self.update_all()

    def update_all(self):
        """update combo index based on current property values. does not emit valueChanged signal."""
        self._block_signals = True
        try:
            # Set combo index based on current property values
            binning_val = None
            decimation_val = None
            try:
                binning_val = self.get_prop(0)
            except Exception:
                pass
            try:
                decimation_val = self.get_prop(2)
            except Exception:
                pass
            idx = 0
            if binning_val == 2:
                idx = 1
            elif decimation_val == 2:
                idx = 2
            self.combo.setCurrentIndex(idx)
        finally:
            self._block_signals = False
