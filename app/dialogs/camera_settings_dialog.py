from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QSizePolicy,
)
from PyQt6.QtCore import Qt
from imagingcontrol4.grabber import Grabber
from imagingcontrol4.propconstants import PropId
from imagingcontrol4.properties import (
    Property,
    PropInteger,
    PropFloat,
    PropEnumeration,
)
from dialogs.controls.props import PropFloatControl, PropEnumerationControl
from dialogs.controls.binningdecimation import BinningDecimationControl

class CameraSettingsDialog(QDialog):
    def __init__(self, grabber: Grabber, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Settings")
        self.grabber = grabber
        self.prop_map = grabber.device_property_map
        layout = QVBoxLayout(self)
        layout.setSpacing(16)  # Increase default spacing between widgets

        # AcquisitionFrameRate
        afr_prop = self.prop_map.find(PropId.ACQUISITION_FRAME_RATE)
        assert isinstance(afr_prop, PropFloat), "Expected PropFloat for Acquisition Frame Rate"
        layout.addWidget(QLabel("Acquisition Frame Rate"))
        layout.addSpacing(12)
        self.afr_control = PropFloatControl(afr_prop, self, grabber)
        self.afr_control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.afr_control)
        layout.addSpacing(12)

        # ExposureAuto
        exp_auto_prop = self.prop_map.find(PropId.EXPOSURE_AUTO)
        assert isinstance(exp_auto_prop, PropEnumeration), "Expected PropEnumeration for Exposure Auto"
        layout.addWidget(QLabel("Exposure Auto"))
        layout.addSpacing(12)
        self.exp_auto_control = PropEnumerationControl(exp_auto_prop, self, grabber)
        self.exp_auto_control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.exp_auto_control)
        layout.addSpacing(12)

        # ExposureTime
        exp_time_prop = self.prop_map.find(PropId.EXPOSURE_TIME)
        assert isinstance(exp_time_prop, PropFloat), "Expected PropFloat for Exposure Time"
        layout.addWidget(QLabel("Exposure Time"))
        layout.addSpacing(12)
        self.exp_time_control = PropFloatControl(exp_time_prop, self, grabber)
        self.exp_time_control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.exp_time_control)
        layout.addSpacing(12)

        # BlackLevel
        black_level_prop = self.prop_map.find(PropId.BLACK_LEVEL)
        assert isinstance(black_level_prop, PropFloat), "Expected PropFloat for Black Level"
        layout.addWidget(QLabel("Black Level"))
        layout.addSpacing(12)
        self.black_level_control = PropFloatControl(black_level_prop, self, grabber)
        self.black_level_control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.black_level_control)
        layout.addSpacing(12)

        # Gamma
        gamma_prop = self.prop_map.find(PropId.GAMMA)
        assert isinstance(gamma_prop, PropFloat), "Expected PropFloat for Gamma"
        layout.addWidget(QLabel("Gamma"))
        layout.addSpacing(12)
        self.gamma_control = PropFloatControl(gamma_prop, self, grabber)
        self.gamma_control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.gamma_control)
        layout.addSpacing(12)

        # GainAuto
        gain_auto_prop = self.prop_map.find(PropId.GAIN_AUTO)
        assert isinstance(gain_auto_prop, PropEnumeration), "Expected PropEnumeration for Gain Auto"
        layout.addWidget(QLabel("Gain Auto"))
        layout.addSpacing(12)
        self.gain_auto_control = PropEnumerationControl(gain_auto_prop, self, grabber)
        self.gain_auto_control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.gain_auto_control)
        layout.addSpacing(12)

        # Gain
        gain_prop = self.prop_map.find(PropId.GAIN)
        assert isinstance(gain_prop, PropFloat), "Expected PropFloat for Gain"
        layout.addWidget(QLabel("Gain"))
        layout.addSpacing(12)
        self.gain_control = PropFloatControl(gain_prop, self, grabber)
        self.gain_control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.gain_control)
        layout.addSpacing(12)

        # Binning/Decimation dropdown (custom logic)
        self.binning_combo = BinningDecimationControl(grabber=self.grabber, parent=self)
        self.binning_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.binning_combo)
        layout.addSpacing(12)

        # Apply button
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.accept)
        self.apply_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.apply_btn)
        layout.addSpacing(16)

        # Connect ExposureAuto to enable/disable ExposureTime
        assert self.exp_auto_control.combo is not None, "Expected combo box in ExposureAuto control"
        self.exp_auto_control.combo.currentIndexChanged.connect(self._update_exposure_time_enabled)
        self._update_exposure_time_enabled(self.exp_auto_control.combo.currentIndex())

    def _update_exposure_time_enabled(self, idx: int):
        self.exp_auto_control._on_combo_changed(idx) # old signal
        assert self.exp_auto_control.combo is not None, "Expected combo box in ExposureAuto control"
        auto_val = self.exp_auto_control.combo.currentText()
        enabled = auto_val == "Off"
        self.exp_time_control.setEnabled(enabled)

    def _on_binning_changed(self, idx):
        if idx == 0:
            self.prop_map.set_value(PropId.BINNING_VERTICAL, 1)
            self.prop_map.set_value(PropId.BINNING_HORIZONTAL, 1)
            self.prop_map.set_value(PropId.DECIMATION_VERTICAL, 1)
            self.prop_map.set_value(PropId.DECIMATION_HORIZONTAL, 1)
        elif idx == 1:
            self.prop_map.set_value(PropId.BINNING_VERTICAL, 2)
            self.prop_map.set_value(PropId.BINNING_HORIZONTAL, 2)
        elif idx == 2:
            self.prop_map.set_value(PropId.DECIMATION_VERTICAL, 2)
            self.prop_map.set_value(PropId.DECIMATION_HORIZONTAL, 2)
