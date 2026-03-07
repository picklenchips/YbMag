"""
Property dialog for viewing and editing device properties.

Supports two layouts controlled by the *tabbed* flag:
  - Tabbed (default): each top-level category gets its own tab, with a global
    search bar and shared info box.
  - Classic: a single property tree with an integrated search bar and info box.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QApplication,
    QVBoxLayout,
    QTabWidget,
    QWidget,
)
from typing import Optional, Union, Dict

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropertyMap
from .controls.tabbed_property_widget import TabbedPropertyWidget
from .controls.property_tree_widget import (
    PropertyTreeWidget,
    PropertyTreeWidgetSettings,
)

from resources.style_manager import get_style_manager


class PropertyDialog(QDialog):
    """Dialog for viewing and adjusting device properties."""

    def __init__(
        self,
        obj: Union[Grabber, PropertyMap],
        parent: Optional[QWidget] = None,
        title: str = "",
        additional_maps: Optional[Dict[str, PropertyMap]] = None,
        resource_selector=None,
        tabbed: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)

        if isinstance(obj, Grabber):
            self._grabber: Optional[Grabber] = obj
            self._map: Optional[PropertyMap] = obj.device_property_map
        else:
            self._grabber = None
            self._map = obj

        self.additional_maps = additional_maps or {}
        self.resource_selector = resource_selector
        self._tabbed = tabbed
        self._extra_trees: list[PropertyTreeWidget] = []

        self._create_ui()

    def _create_ui(self):
        self.setMinimumSize(500, 700)
        layout = QVBoxLayout(self)

        assert self._map is not None

        if self._tabbed:
            self._widget: Union[TabbedPropertyWidget, PropertyTreeWidget] = (
                TabbedPropertyWidget(
                    property_map=self._map,
                    grabber=self._grabber,
                    additional_maps=self.additional_maps,
                    parent=self,
                )
            )
            layout.addWidget(self._widget)
        else:
            root = self._map.find_category("Root")
            settings = PropertyTreeWidgetSettings(
                show_root_item=False,
                show_info_box=True,
                show_filter=True,
            )
            primary = PropertyTreeWidget(root, self._grabber, settings, self)
            self._widget = primary

            if self.additional_maps:
                # Wrap in tabs so additional maps (e.g. Codec Settings) are reachable
                tabs = QTabWidget()
                tabs.addTab(primary, "Properties")
                for tab_name, pmap in self.additional_maps.items():
                    extra_root = pmap.find_category("Root")
                    extra = PropertyTreeWidget(extra_root, None, settings, self)
                    self._extra_trees.append(extra)
                    tabs.addTab(extra, tab_name)
                layout.addWidget(tabs)
            else:
                layout.addWidget(primary)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    # ── Public API ─────────────────────────────────────────────────

    def update_grabber(self, grabber: Grabber):
        """Update with a new grabber (new device)."""
        self._grabber = grabber
        self._map = grabber.device_property_map
        if isinstance(self._widget, TabbedPropertyWidget):
            self._widget.update_grabber(grabber)
        else:
            self._widget.update_grabber(grabber)

    def update_property_map(self, property_map: PropertyMap):
        """Update with a new property map."""
        self._map = property_map
        self._grabber = None
        if isinstance(self._widget, TabbedPropertyWidget):
            self._widget._property_map = property_map
            self._widget._grabber = None
            self._widget._populate_tabs()
        else:
            self._widget.update_model(property_map.find_category("Root"))

    def clear_all(self):
        """Drop all models – call before closing the device."""
        if isinstance(self._widget, TabbedPropertyWidget):
            self._widget.clear_all()
        else:
            self._widget.clear_model()
        for tree in self._extra_trees:
            tree.clear_model()
        self._extra_trees.clear()
        # Release references to additional PropertyMap objects so they can be
        # garbage collected before the IC4 Library context is torn down
        self.additional_maps.clear()
        self._map = None
        self._grabber = None

    def set_filter_text(self, filter_text: str):
        """Set the search text."""
        self._widget.set_filter_text(filter_text)

    def apply_theme(self) -> None:
        """Apply the current theme to this dialog."""
        style_manager = get_style_manager()
        if self.resource_selector:
            style_manager.apply_theme(self.resource_selector.get_theme())
        else:
            style_manager.apply_theme()

        self.update()
        if self._widget:
            self._widget.update()
        for tree in self._extra_trees:
            tree.update()

        app = QApplication.instance()
        if app:
            for widget in [self, self._widget, *self._extra_trees]:
                if widget:
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
