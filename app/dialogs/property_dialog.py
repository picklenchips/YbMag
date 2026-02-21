"""
Property dialog for viewing and editing device properties
Translated from C++ PropertyDialog.h/cpp
"""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)
from typing import Optional, Union, Dict

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropertyMap, PropertyVisibility, PropCategory
from .controls.property_tree_widget import (
    PropertyTreeWidget,
    PropertyTreeWidgetSettings,
)

from resources.style_manager import get_style_manager


class PropertyDialog(QDialog):
    """Dialog for viewing and adjusting device properties"""

    def __init__(
        self,
        obj: Union[Grabber, PropertyMap],
        parent: Optional[QWidget] = None,
        title: str = "",
        additional_maps: Optional[Dict[str, PropertyMap]] = None,
        resource_selector=None,
    ):
        super().__init__(parent)

        self.setWindowTitle(title)

        # Determine if we have a grabber or property map
        if isinstance(obj, Grabber):
            self._grabber = obj
            self._map = obj.device_property_map
        else:
            self._grabber = None
            self._map = obj

        # Store additional property maps (e.g., for codec settings)
        self.additional_maps = additional_maps or {}
        self.resource_selector = resource_selector

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

        # Close button (matches C++ QDialogButtonBox::Close)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        main_layout.addWidget(buttons)

        self.setLayout(main_layout)

    def _create_tree_widget(
        self,
        property_map: PropertyMap,
        root_name: str,
        grabber: Optional[Grabber],
    ) -> PropertyTreeWidget:
        """Create a property tree widget for the given property map"""
        root_category = property_map.find_category(root_name)

        settings = PropertyTreeWidgetSettings(
            show_root_item=False,
            show_info_box=True,
            show_filter=True,
            initial_visibility=PropertyVisibility.BEGINNER,
        )

        return PropertyTreeWidget(root_category, grabber, settings, self)

    def update_grabber(self, grabber: Grabber):
        """Update with a new grabber"""
        self._map = grabber.device_property_map
        self._grabber = grabber

        if self._tree:
            self._tree.update_grabber(grabber)

    def update_property_map(self, property_map: PropertyMap):
        """Update with a new property map"""
        self._map = property_map
        self._grabber = None

        if self._tree:
            self._tree.update_model(property_map.find_category("Root"))

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
            style_manager = get_style_manager()
            style_manager.apply_theme(self.resource_selector.get_theme())
