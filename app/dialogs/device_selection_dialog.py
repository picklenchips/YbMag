"""
Device selection dialog
Simplified translation from C++ DeviceSelectionDialog.h/cpp
"""

from PyQt6.QtCore import Qt, QEvent, QSize
from PyQt6.QtWidgets import (
    QDialog,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QApplication,
    QScrollArea,
    QGroupBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QFrame,
    QStyle,
)
from PyQt6.QtGui import QIcon
from typing import Optional, Callable, Dict, Any

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.devenum import DeviceEnum, DeviceInfo, TransportLayerType
from imagingcontrol4.library import Library

# local imports
from resources.style_manager import get_style_manager


class DeviceSelectionDialog(QDialog):
    """Dialog for selecting a camera device"""

    # Custom event type for device list changed
    EVENT_DEVICE_LIST_CHANGED = QEvent.Type.User + 3

    def __init__(
        self,
        grabber: Grabber,
        parent: Optional[QWidget] = None,
        filter_func: Optional[Callable[[DeviceInfo], bool]] = None,
        resource_selector=None,
    ):
        super().__init__(parent)

        self.grabber = grabber
        self.filter_func = filter_func
        self.enumerator = DeviceEnum()
        self.resource_selector = resource_selector

        self._create_ui()
        self._on_refresh()

        # Register for device list changes
        try:
            self.enumerator.event_add_device_list_changed(
                lambda enum: QApplication.postEvent(
                    self, QEvent(DeviceSelectionDialog.EVENT_DEVICE_LIST_CHANGED)
                )
            )
        except Exception:
            pass

    def customEvent(self, event: QEvent):
        """Handle custom events"""
        if event.type() == DeviceSelectionDialog.EVENT_DEVICE_LIST_CHANGED:
            self._on_refresh()

    def _create_ui(self):
        """Create the dialog UI"""
        self.setWindowTitle("Select Device")
        self.setMinimumSize(900, 550)

        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()

        # Create tree widget
        self.camera_tree = QTreeWidget()
        self.camera_tree.setIconSize(QSize(24, 24))
        self.camera_tree.setIndentation(16)
        self.camera_tree.setRootIsDecorated(True)
        self.camera_tree.setMinimumWidth(450)
        self.camera_tree.setItemsExpandable(True)

        self.camera_tree.setColumnCount(4)
        self.camera_tree.setHeaderLabels(
            ["Device", "Serial Number", "IP Address", "Device User ID"]
        )
        self.camera_tree.setColumnWidth(0, 160)
        self.camera_tree.setColumnWidth(1, 100)
        self.camera_tree.setColumnWidth(2, 100)
        self.camera_tree.setColumnWidth(3, 80)

        self.camera_tree.currentItemChanged.connect(self._on_current_item_changed)
        self.camera_tree.itemDoubleClicked.connect(lambda item, col: self._on_ok())

        left_layout.addWidget(self.camera_tree)

        # Create buttons
        button_layout = QHBoxLayout()

        system_info_button = QPushButton("System Info")
        system_info_button.clicked.connect(self._on_system_info)
        button_layout.addWidget(system_info_button)

        refresh_button = QPushButton("Refresh (F5)")
        refresh_button.clicked.connect(self._on_refresh)
        refresh_button.setShortcut("F5")
        button_layout.addWidget(refresh_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        self.ok_button = QPushButton("OK")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self._on_ok)
        self.ok_button.setEnabled(False)
        button_layout.addWidget(self.ok_button)

        left_layout.addLayout(button_layout)
        main_layout.addLayout(left_layout, 1)

        # Create right-side information panel
        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setMinimumWidth(350)

        right_widget = QWidget()
        self.right_layout = QVBoxLayout(right_widget)
        self.right_layout.setSpacing(10)

        # Create info group boxes (initially hidden)
        self.interface_info_group = self._create_info_group("Interface Information")
        self.device_info_group = self._create_info_group("Device Information")

        self.right_layout.addWidget(self.interface_info_group)
        self.right_layout.addWidget(self.device_info_group)
        self.right_layout.addStretch()

        self.right_scroll.setWidget(right_widget)
        main_layout.addWidget(self.right_scroll, 2)

        self.setLayout(main_layout)

    def _create_info_group(self, title: str) -> QGroupBox:
        """Create an information group box with form layout"""
        group = QGroupBox(title)
        group.setVisible(False)
        layout = QFormLayout()
        group.setLayout(layout)
        return group

    def _enumerate_devices(self):
        """Enumerate and populate device tree"""
        self.camera_tree.clear()

        try:
            interfaces = DeviceEnum.interfaces()
        except Exception as e:
            print(f"Error enumerating interfaces: {e}")
            interfaces = []

        if not interfaces:
            item = QTreeWidgetItem(self.camera_tree)
            item.setText(0, "No interfaces found.")
            item.setDisabled(True)
            return

        any_devices = False
        num_displayed = 0

        for itf in interfaces:
            try:
                itf_devices = itf.devices
                any_devices = any_devices or len(itf_devices) > 0

                # Apply filter
                if self.filter_func:
                    filtered_devices = [d for d in itf_devices if self.filter_func(d)]
                else:
                    filtered_devices = itf_devices

                if not filtered_devices:
                    continue

                # Create interface item
                itf_item = QTreeWidgetItem(self.camera_tree)
                itf_item.setText(0, itf.display_name)
                itf_item.setData(0, Qt.ItemDataRole.UserRole, {"interface": itf})
                itf_item.setFirstColumnSpanned(True)

                # Check if GigE Vision
                try:
                    is_gige = itf.transport_layer_type == TransportLayerType.GIGEVISION
                except Exception:
                    is_gige = False

                # Get interface property map for IP addresses
                try:
                    itf_map = itf.property_map
                except Exception:
                    itf_map = None

                # Add devices
                for idx, dev in enumerate(filtered_devices):
                    device_item = QTreeWidgetItem()

                    # Get device info
                    try:
                        model = dev.model_name
                        serial = dev.serial
                        user_id = dev.user_id
                    except Exception:
                        model = "Unknown"
                        serial = ""
                        user_id = ""

                    device_item.setText(0, model)
                    device_item.setText(1, serial)
                    device_item.setText(3, user_id)

                    # Find device index in original list
                    try:
                        orig_idx = itf_devices.index(dev)
                    except Exception:
                        orig_idx = idx

                    # Get IP address and reachable status for GigE devices
                    is_reachable = True
                    if is_gige and itf_map:
                        try:
                            itf_map.set_value("DeviceSelector", orig_idx)
                            ip = itf_map.get_value_int("GevDeviceIPAddress")
                            ip_str = f"{(ip >> 24) & 0xFF}.{(ip >> 16) & 0xFF}.{(ip >> 8) & 0xFF}.{(ip >> 0) & 0xFF}"
                            device_item.setText(2, ip_str)

                            # Check reachable status
                            try:
                                reachable_status = itf_map.get_value_str(
                                    "DeviceReachableStatus"
                                )
                                is_reachable = reachable_status == "Reachable"
                            except Exception:
                                pass
                        except Exception:
                            pass

                    # Set icon based on reachable status
                    if is_reachable:
                        # Use default camera icon (you can customize this)
                        pass
                    elif style := self.style():
                        # Show warning icon for unreachable devices
                        warning_icon = style.standardIcon(
                            QStyle.StandardPixmap.SP_MessageBoxWarning
                        )
                        device_item.setIcon(0, warning_icon)

                    # Store device info
                    device_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {
                            "device": dev,
                            "interface": itf,
                            "interface_map": itf_map,
                            "device_index": orig_idx,
                            "is_device": True,
                            "is_reachable": is_reachable,
                        },
                    )

                    itf_item.addChild(device_item)
                    num_displayed += 1

                # Expand interface
                itf_item.setExpanded(True)

            except Exception as e:
                print(f"Error processing interface: {e}")

        if num_displayed == 0 and any_devices:
            item = QTreeWidgetItem(self.camera_tree)
            item.setText(0, "No devices match the filter.")
            item.setDisabled(True)

    def _on_refresh(self):
        """Refresh device list"""
        # Save current selection
        previous_data = None
        current = self.camera_tree.currentItem()
        if current:
            previous_data = current.data(0, Qt.ItemDataRole.UserRole)

        self._enumerate_devices()

        # Try to restore previous selection
        if previous_data:
            self._select_previous_item(previous_data)

    def _select_previous_item(self, previous_data: Dict[str, Any]) -> bool:
        """Try to re-select the previously selected item after refresh"""
        if not previous_data:
            return False

        # Iterate through tree to find matching item
        for i in range(self.camera_tree.topLevelItemCount()):
            if not (itf_item := self.camera_tree.topLevelItem(i)):
                continue
            if not previous_data.get("is_device", False):
                # Was an interface item
                item_data = itf_item.data(0, Qt.ItemDataRole.UserRole)
                if item_data and item_data.get("interface") == previous_data.get(
                    "interface"
                ):
                    self.camera_tree.setCurrentItem(itf_item)
                    return True
            else:
                # Was a device item
                for j in range(itf_item.childCount()):
                    if not (dev_item := itf_item.child(j)):
                        continue
                    item_data = dev_item.data(0, Qt.ItemDataRole.UserRole)
                    if item_data and item_data.get("device") == previous_data.get(
                        "device"
                    ):
                        self.camera_tree.setCurrentItem(dev_item)
                        return True

        return False

    def _on_current_item_changed(
        self, current: QTreeWidgetItem, previous: QTreeWidgetItem
    ):
        """Handle current item change"""
        # Clear info panels
        self._clear_info_group(self.interface_info_group)
        self._clear_info_group(self.device_info_group)
        self.interface_info_group.setVisible(False)
        self.device_info_group.setVisible(False)

        if not current:
            self.ok_button.setEnabled(False)
            return

        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            self.ok_button.setEnabled(False)
            return

        # Show interface information
        if "interface" in data:
            self._populate_interface_info(data)

        # Show device information and enable OK button if it's a device
        if data.get("is_device", False):
            is_reachable = data.get("is_reachable", True)
            self.ok_button.setEnabled(is_reachable)
            self._populate_device_info(data)
        else:
            self.ok_button.setEnabled(False)

    def _clear_info_group(self, group: QGroupBox):
        """Clear all items from an info group"""
        if layout := group.layout():
            while layout.count():
                item = layout.takeAt(0)
                if item and (widget := item.widget()):
                    widget.deleteLater()

    def _add_info_item(self, group: QGroupBox, label: str, value: str):
        """Add an information item to a group box"""
        layout = group.layout()
        if isinstance(layout, QFormLayout):
            line_edit = QLineEdit(value)
            line_edit.setReadOnly(True)
            line_edit.setCursorPosition(0)
            layout.addRow(label, line_edit)

    def _populate_interface_info(self, data: Dict[str, Any]):
        """Populate interface information panel"""
        itf = data.get("interface")
        if not itf:
            return

        self.interface_info_group.setVisible(True)

        try:
            self._add_info_item(
                self.interface_info_group, "Interface Name", itf.display_name
            )
        except Exception:
            pass

        # Get interface property map for additional info
        try:
            itf_map = itf.property_map

            # Show IP addresses for GigE interfaces
            try:
                if itf.transport_layer_type == TransportLayerType.GIGEVISION:
                    # Try to get interface IP
                    try:
                        ip_addr = itf_map.get_value_string(
                            "GevInterfaceSubnetIPAddress"
                        )
                        self._add_info_item(
                            self.interface_info_group, "IP Address", ip_addr
                        )
                    except Exception:
                        pass

                    # Try to get MTU
                    try:
                        mtu = itf_map.get_value_string("MaximumTransmissionUnit")
                        self._add_info_item(
                            self.interface_info_group, "Maximum Transmission Unit", mtu
                        )
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass

        # Add transport layer info
        try:
            tl_name = itf.transport_layer_name
            if tl_name:
                self._add_info_item(self.interface_info_group, "Driver Name", tl_name)
        except Exception:
            pass

        try:
            tl_version = itf.transport_layer_version
            if tl_version:
                self._add_info_item(
                    self.interface_info_group, "Driver Version", tl_version
                )
        except Exception:
            pass

    def _populate_device_info(self, data: Dict[str, Any]):
        """Populate device information panel"""
        dev = data.get("device")
        itf_map = data.get("interface_map")
        dev_index = data.get("device_index", 0)
        itf = data.get("interface")

        if not dev:
            return

        self.device_info_group.setVisible(True)

        # Set device selector if we have interface map
        if itf_map:
            try:
                itf_map.set_value("DeviceSelector", dev_index)
            except Exception:
                pass

        # Basic device info
        try:
            self._add_info_item(self.device_info_group, "Model Name", dev.model_name)
        except Exception:
            pass

        try:
            self._add_info_item(self.device_info_group, "Vendor Name", dev.vendor)
        except Exception:
            pass

        try:
            self._add_info_item(self.device_info_group, "Serial Number", dev.serial)
        except Exception:
            pass

        try:
            self._add_info_item(self.device_info_group, "Device Version", dev.version)
        except Exception:
            pass

        try:
            user_id = dev.user_id
            if user_id:
                self._add_info_item(self.device_info_group, "Device User ID", user_id)
        except Exception:
            pass

        # GigE-specific info
        if itf_map:
            try:
                if itf and itf.transport_layer_type == TransportLayerType.GIGEVISION:
                    # Device IP Address
                    try:
                        ip = itf_map.get_value_int("GevDeviceIPAddress")
                        ip_str = f"{(ip >> 24) & 0xFF}.{(ip >> 16) & 0xFF}.{(ip >> 8) & 0xFF}.{ip & 0xFF}"
                        self._add_info_item(
                            self.device_info_group, "Device IP Address", ip_str
                        )
                    except Exception:
                        pass

                    # Gateway
                    try:
                        gateway = itf_map.get_value_string("GevDeviceGateway")
                        self._add_info_item(
                            self.device_info_group, "Device Gateway", gateway
                        )
                    except Exception:
                        pass

                    # MAC Address
                    try:
                        mac = itf_map.get_value_string("GevDeviceMACAddress")
                        self._add_info_item(
                            self.device_info_group, "Device MAC Address", mac
                        )
                    except Exception:
                        pass
            except Exception:
                pass

    def _on_system_info(self):
        """Show system information dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("System Info")
        dialog.setMinimumSize(640, 480)

        layout = QVBoxLayout()

        # Create text edit with system info
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(self._build_system_info())
        layout.addWidget(text_edit)

        # Buttons
        button_layout = QHBoxLayout()

        copy_button = QPushButton("Copy to Clipboard")
        copy_button.clicked.connect(
            lambda: (
                text_edit.selectAll(),
                text_edit.copy(),
                copy_button.setText("Copied!"),
            )
        )
        button_layout.addWidget(copy_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)
        dialog.setLayout(layout)

        dialog.exec()

    def _build_system_info(self) -> str:
        """Build system information string"""
        info = []

        # Application info
        app_name = QApplication.applicationDisplayName()
        app_version = QApplication.applicationVersion()
        if app_name:
            info.append(f"Application: {app_name}")
            if app_version:
                info.append(f"Version: {app_version}")
            info.append("")

        # IC4 version info
        try:
            version_info = Library.get_version_info()
            info.append(f"imagingcontrol4 Version: {version_info}")
            info.append("")
        except Exception as e:
            info.append(f"Version info unavailable: {e}")
            info.append("")

        # Detected interfaces and devices
        info.append("Detected Interfaces/Devices:")
        try:
            interfaces = DeviceEnum.interfaces()
            if not interfaces:
                info.append("  No interfaces found")
            else:
                for itf in interfaces:
                    try:
                        info.append(f"  {itf.display_name}")
                        devices = itf.devices
                        if not devices:
                            info.append("    (No devices)")
                        else:
                            for dev in devices:
                                try:
                                    info.append(
                                        f"    - {dev.model_name} [{dev.serial}]"
                                    )
                                except Exception:
                                    info.append("    - (Unknown device)")
                    except Exception as e:
                        info.append(f"    Error: {e}")
                    info.append("")
        except Exception as e:
            info.append(f"  Failed to enumerate interfaces: {e}")

        return "\n".join(info)

    def _on_ok(self):
        """Open selected device"""
        current = self.camera_tree.currentItem()
        if not current:
            return

        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data or not data.get("is_device", False):
            return

        device = data.get("device")
        if not device:
            return

        # Check if device is reachable
        is_reachable = data.get("is_reachable", True)
        if not is_reachable:
            QMessageBox.warning(
                self,
                "Device Not Reachable",
                "The selected device is not reachable. Please check network configuration.",
            )
            return

        print(
            f"[_on_ok] is_device_open={self.grabber.is_device_open}, is_streaming={self.grabber.is_streaming}"
        )

        try:
            # Check if selected device is already open
            already_open = False
            if self.grabber.is_device_open:
                try:
                    current_device_info = self.grabber.device_info
                    # Compare using unique_name which uniquely identifies a device
                    if current_device_info.unique_name == device.unique_name:
                        already_open = True
                        print("[_on_ok] Same device already open, accepting")
                except Exception as e:
                    print(f"[_on_ok] unique_name comparison failed: {e}")

            if already_open:
                # Already connected to this device, just close dialog
                self.accept()
                return

            # Close existing device if one is open
            if self.grabber.is_device_open:
                print("[_on_ok] Closing existing device before opening new one")
                try:
                    self.grabber.stream_stop()
                except Exception as e:
                    print(f"[_on_ok] stream_stop() error: {e}")
                self.grabber.device_close()
                print(
                    f"[_on_ok] device_close() done, is_device_open={self.grabber.is_device_open}"
                )

                # Force garbage collection to ensure C++ resources are released
                import gc

                print("[_on_ok] Running garbage collection...")
                gc.collect()
                print("[_on_ok] GC complete")

            print(f"[_on_ok] Opening device: {device.model_name} [{device.serial}]")
            self.grabber.device_open(device)
            print(
                f"[_on_ok] device_open() succeeded, is_device_open={self.grabber.is_device_open}"
            )
            self.accept()
        except Exception as e:
            print(f"[_on_ok] FAILED: {e}")
            QMessageBox.critical(
                self, "Error Opening Device", f"Failed to open device:\n{str(e)}"
            )

    def apply_theme(self) -> None:
        """Apply the current theme to this dialog"""
        if self.resource_selector:
            style_manager = get_style_manager()
            style_manager.apply_theme(self.resource_selector.get_theme())
