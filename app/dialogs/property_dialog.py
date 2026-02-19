"""
Property dialog for viewing and editing device properties
Translated from C++ PropertyDialog.h/cpp
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)
from typing import Optional, Union, Any, Dict

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropertyMap, PropertyVisibility, PropCategory
from .controls.property_tree_widget import (
    PropertyTreeWidget,
    PropertyTreeWidgetSettings,
)


class PropertyDialog(QDialog):
    """Dialog for viewing and adjusting device properties"""

    def __init__(
        self,
        obj: Union[Grabber, PropertyMap],
        parent: Optional[QWidget] = None,
        title: str = "Device Properties",
        resource_selector: Optional[Any] = None,
        additional_maps: Optional[Dict[str, PropertyMap]] = None,
    ):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.resource_selector = resource_selector

        # Determine if we have a grabber or property map
        if isinstance(obj, Grabber):
            self._grabber = obj
            self._map = obj.device_property_map
        else:
            self._grabber = None
            self._map = obj

        # Store additional property maps (e.g., for codec settings)
        self.additional_maps = additional_maps or {}

        # Store tree widgets for each property map
        self._trees: Dict[str, PropertyTreeWidget] = {}

        self._create_ui()

    def _create_ui(self):
        """Create the dialog UI"""
        self.setMinimumSize(500, 700)

        main_layout = QVBoxLayout()

        # Create property tree widget for main property map
        primary_tree = self._create_tree_widget(self._map, "Root", self._grabber)

        if primary_tree:
            self._tree = primary_tree
            self._trees["Properties"] = primary_tree

            # If there are additional maps, create a tab widget
            if self.additional_maps:
                tab_widget = QTabWidget()
                tab_widget.addTab(primary_tree, "Properties")

                for tab_name, prop_map in self.additional_maps.items():
                    additional_tree = self._create_tree_widget(prop_map, "Root", None)
                    if additional_tree:
                        tab_widget.addTab(additional_tree, tab_name)
                        self._trees[tab_name] = additional_tree

                main_layout.addWidget(tab_widget)
            else:
                main_layout.addWidget(primary_tree)
        else:
            self._tree = None

        self.setLayout(main_layout)

    def _create_tree_widget(
        self,
        property_map: PropertyMap,
        root_name: str,
        grabber: Optional[Grabber],
    ) -> Optional[PropertyTreeWidget]:
        """Create a property tree widget for the given property map"""
        try:
            root_category = property_map.find_category(root_name)
        except Exception:
            # If no Root category, try to use the map directly
            try:
                root_category = property_map
            except Exception:
                return None

        settings = PropertyTreeWidgetSettings(
            show_root_item=False,
            show_info_box=True,
            show_filter=True,
        )

        if root_category:
            assert isinstance(
                root_category, PropCategory
            ), f"Root item must be a category but was {type(root_category)}"
            return PropertyTreeWidget(root_category, grabber, settings, self)
        return None

    def update_grabber(self, grabber: Grabber):
        """Update with a new grabber"""
        self._grabber = grabber
        self._map = grabber.device_property_map

        if self._tree:
            try:
                root_category = self._map.find_category("Root")
                self._tree.update_model(root_category)
            except Exception:
                pass

    def update_property_map(self, property_map: PropertyMap):
        """Update with a new property map"""
        self._map = property_map
        self._grabber = None

        if self._tree:
            try:
                root_category = property_map.find_category("Root")
                self._tree.update_model(root_category)
            except Exception:
                pass

    def set_prop_visibility(self, vis: PropertyVisibility):
        """Set the visibility filter"""
        if self._tree:
            self._tree.set_prop_visibility(vis)

    def set_filter_text(self, filter_text: str):
        """Set the filter text"""
        if self._tree:
            self._tree.set_filter_text(filter_text)

    def apply_theme(self) -> None:
        """Apply the current theme to this dialog"""
        if self.resource_selector:
            self.resource_selector.apply_theme(self)
            # Ensure all tree widgets and their children get the theme
            for tree in self._trees.values():
                tree.setPalette(self.palette())
                # Force update of all tree items with new palette
                tree.view_.update()
