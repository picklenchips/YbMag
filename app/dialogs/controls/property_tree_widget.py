"""
Property tree widget
Translated from C++ PropertyTreeWidget.h/cpp
"""

from PyQt6.QtCore import Qt, QRect, QItemSelectionModel
from PyQt6.QtWidgets import (
    QWidget,
    QTreeView,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QLineEdit,
    QLabel,
    QStyledItemDelegate,
    QSplitter,
)
from PyQt6.QtGui import QPainter, QMouseEvent, QShortcut, QKeySequence
from imagingcontrol4.properties import PropertyVisibility, PropCategory
from imagingcontrol4.grabber import Grabber
from typing import Optional, Callable
from dataclasses import dataclass

from .property_tree_model import (
    PropertyTreeModel,
    FilterPropertiesProxy,
    PropertyTreeNode,
)
from .property_controls import create_prop_control
from .props.prop_control_base import StreamRestartFilterFunction, PropSelectedFunction
from .property_info_box import PropertyInfoBox


class PropertyTreeItemDelegate(QStyledItemDelegate):
    """Delegate for creating editors in the tree"""

    def __init__(
        self,
        proxy: FilterPropertiesProxy,
        grabber: Optional[Grabber],
        restart_filter: Optional[StreamRestartFilterFunction],
        prop_selected: Optional[PropSelectedFunction],
    ):
        super().__init__()
        self.proxy_ = proxy
        self.grabber_ = grabber
        self.restart_filter_ = restart_filter
        self.prop_selected_ = prop_selected

    def update_grabber(self, grabber: Optional[Grabber]):
        """Update grabber reference"""
        self.grabber_ = grabber

    def sizeHint(self, option, index):
        """Return size hint for items - ensures rows are tall enough for widgets"""
        from PyQt6.QtCore import QSize

        # Get the default size hint from the base class
        size = super().sizeHint(option, index)

        # Ensure minimum height for all rows to accommodate widgets
        # QComboBox and other controls typically need at least 28-32 pixels
        min_height = 32

        if size.height() < min_height:
            size.setHeight(min_height)

        return size

    def createEditor(self, parent: QWidget, option, index) -> Optional[QWidget]:
        """Create editor widget for property"""
        source_index = self.proxy_.mapToSource(index)
        tree = source_index.internalPointer()

        if not tree:
            return None

        widget = create_prop_control(
            tree.prop, parent, self.grabber_, self.restart_filter_, self.prop_selected_
        )

        if widget:
            widget.setContentsMargins(4, 2, 8, 2)  # Add padding around value controls

        return widget


class PropertyTreeView(QTreeView):
    """Custom tree view for properties"""

    def __init__(self, proxy: FilterPropertiesProxy):
        super().__init__()
        self.proxy_ = proxy

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press to toggle expansion"""
        index = self.indexAt(event.pos())
        last_state = self.isExpanded(index)
        super().mousePressEvent(event)
        if index.isValid() and last_state == self.isExpanded(index):
            self.setExpanded(index, not last_state)

    def drawBranches(self, painter: QPainter, rect: QRect, index):
        """Custom branch drawing for categories"""
        source_index = self.proxy_.mapToSource(index)
        tree = source_index.internalPointer()

        if tree and len(tree.children) > 0:
            # Draw category background
            painter.fillRect(rect, self.palette().mid())

            # Draw expand/collapse indicator
            offset = (rect.width() - self.indentation()) // 2
            x = rect.x() + rect.width() // 2 + offset
            y = rect.y() + rect.height() // 2
            length = 9

            color = self.palette().text().color()

            if self.isExpanded(index):
                # Draw down arrow
                x = x - 5
                y = y - 2
                for i in range(5):
                    arrow_rect = QRect(x + i, y + i, length - (i * 2), 1)
                    painter.fillRect(arrow_rect, color)
            else:
                # Draw right arrow
                x = x - 2
                y = y - 5
                for i in range(5):
                    arrow_rect = QRect(x + i, y + i, 1, length - (i * 2))
                    painter.fillRect(arrow_rect, color)
        else:
            super().drawBranches(painter, rect, index)


class BranchPaintDelegate(QStyledItemDelegate):
    """Delegate for painting category branches"""

    def __init__(self, proxy: FilterPropertiesProxy, parent: QWidget):
        super().__init__()
        self.proxy_ = proxy
        self.parent_ = parent

    def paint(self, painter: QPainter, option, index):
        """Custom painting for categories"""
        source_index = self.proxy_.mapToSource(index)
        tree = source_index.internalPointer()

        if tree and len(tree.children) > 0:
            # Paint category row
            painter.save()
            painter.setPen(self.parent_.palette().text().color())

            rect = option.rect
            painter.fillRect(rect, self.parent_.palette().mid())
            painter.drawText(rect, option.displayAlignment, index.data())

            painter.restore()
        else:
            super().paint(painter, option, index)


@dataclass
class PropertyTreeWidgetSettings:
    """Settings for property tree widget"""

    show_root_item: bool = False
    show_info_box: bool = True
    show_filter: bool = True
    initial_filter: str = ""
    initial_visibility: PropertyVisibility = PropertyVisibility.GURU
    stream_restart_filter: Optional[StreamRestartFilterFunction] = None


class PropertyTreeWidget(QWidget):
    """Main property tree widget"""

    def __init__(
        self,
        cat: PropCategory,
        grabber: Optional[Grabber],
        settings: Optional[PropertyTreeWidgetSettings] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        if settings is None:
            settings = PropertyTreeWidgetSettings()

        self.settings_ = settings
        self.grabber_ = grabber

        # Create model and proxy
        try:
            self.source_ = PropertyTreeModel(cat, self)
        except Exception as e:
            print(f"[PropertyTreeWidget] Error creating PropertyTreeModel: {e}")
            import traceback

            traceback.print_exc()

        self.proxy_ = FilterPropertiesProxy(self)
        self.proxy_.setSourceModel(self.source_)

        # Create info box and wire up property selection callback
        self.info_box_ = None
        prop_selected_func = None
        if settings.show_info_box:
            self.info_box_ = PropertyInfoBox(self)
            prop_selected_func = lambda prop: (
                self.info_box_.update(prop) if self.info_box_ else None
            )

        # Create delegates
        self.delegate_ = PropertyTreeItemDelegate(
            self.proxy_, grabber, settings.stream_restart_filter, prop_selected_func
        )
        self.branch_paint_delegate_ = BranchPaintDelegate(self.proxy_, self)

        # Create tree view
        self.view_ = PropertyTreeView(self.proxy_)
        self.view_.setModel(self.proxy_)
        self.view_.setItemDelegateForColumn(0, self.branch_paint_delegate_)
        self.view_.setItemDelegateForColumn(1, self.delegate_)
        self.view_.setUniformRowHeights(False)
        self.view_.setAlternatingRowColors(False)

        # Configure header for better spacing
        if header := self.view_.header():
            header.setStretchLastSection(True)
            header.setSectionResizeMode(0, header.ResizeMode.ResizeToContents)

        self.view_.setHeaderHidden(True)  # Hide the column header row
        self.view_.setIndentation(20)  # Set indentation for tree structure

        # Add spacing between items
        self.view_.setStyleSheet(
            """
            QTreeView::item {
                padding: 4px;
                margin: 2px 0px;
            }
        """
        )

        # Create filter controls
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)

        if settings.show_filter:
            filter_layout = QHBoxLayout()
            filter_layout.setSpacing(8)

            # Search box (full width)
            self.filter_text_ = QLineEdit()
            self.filter_text_.setPlaceholderText("Search Properties (Ctrl+F)")
            self.filter_text_.setText(settings.initial_filter)
            self.filter_text_.setClearButtonEnabled(True)
            self.filter_text_.textChanged.connect(self._update_visibility)
            filter_layout.addWidget(self.filter_text_)

            # Add Ctrl+F shortcut to focus search box
            search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
            search_shortcut.activated.connect(
                lambda: (
                    self.filter_text_.setFocus(Qt.FocusReason.ShortcutFocusReason)
                    if self.filter_text_
                    else None
                )
            )

            main_layout.addLayout(filter_layout)
        else:
            self.filter_text_ = None

        self.visibility_combo_ = None  # No longer used

        # Add tree view and info box with splitter if show_info_box is enabled
        if settings.show_info_box and self.info_box_:
            splitter = QSplitter(Qt.Orientation.Vertical, self)
            splitter.addWidget(self.view_)
            splitter.addWidget(self.info_box_)
            splitter.setStretchFactor(0, 3)  # Tree view takes more space
            splitter.setStretchFactor(1, 1)  # Info box takes less space
            main_layout.addWidget(splitter)
        else:
            main_layout.addWidget(self.view_)

        self.setLayout(main_layout)

        # Connect tree view selection to update info box
        if self.info_box_:
            if selectionmodel := self.view_.selectionModel():
                selectionmodel.selectionChanged.connect(self._on_selection_changed)

        # Set root index but don't expand categories by default
        if not settings.show_root_item:
            root_index = self.proxy_.mapFromSource(self.source_.rootIndex())
            self.view_.setRootIndex(root_index)

        # Create all editors
        self._create_all_editors(self.proxy_, self.view_.rootIndex())

        # Apply initial filter
        self._update_visibility()

    def closeEvent(self, event):
        """Clean up when widget is closed"""
        # Close all persistent editors to trigger cleanup
        self._close_all_editors(self.proxy_, self.view_.rootIndex())
        super().closeEvent(event)

    def _close_all_editors(self, model, parent):
        """Recursively close all persistent editors"""
        rows = model.rowCount(parent)

        for row in range(rows):
            index1 = model.index(row, 1, parent)
            if index1.isValid():
                self.view_.closePersistentEditor(index1)

            index0 = model.index(row, 0, parent)
            if index0.isValid():
                self._close_all_editors(model, index0)

    def _create_all_editors(self, model, parent):
        """Recursively create persistent editors for all items"""
        rows = model.rowCount(parent)

        for row in range(rows):
            index0 = model.index(row, 0, parent)
            index1 = model.index(row, 1, parent)

            if index0.isValid():
                # Check if this is a category (has children)
                source_index = self.proxy_.mapToSource(index0)
                tree = source_index.internalPointer()

                if tree and len(tree.children) > 0:
                    # This is a category - span it across both columns
                    self.view_.setFirstColumnSpanned(row, parent, True)
                elif index1.isValid():
                    # This is a property - create editor in column 1
                    self.view_.openPersistentEditor(index1)

                # Recurse into children
                self._create_all_editors(model, index0)

    def _update_visibility(self):
        """Update filter based on current settings"""
        if self.filter_text_:
            # Always use GURU visibility to show all properties
            vis = PropertyVisibility.GURU
            text = self.filter_text_.text()
            self.proxy_.filter(text, vis)

            # Re-establish root index after filtering to ensure root stays hidden
            if not self.settings_.show_root_item:
                root_index = self.proxy_.mapFromSource(self.source_.rootIndex())
                self.view_.setRootIndex(root_index)

    def _on_selection_changed(self, selected, deselected):
        """Handle tree view selection changes to update info box"""
        if not self.info_box_:
            return

        if selectionmodel := self.view_.selectionModel():
            indexes = selectionmodel.selectedIndexes()
        if indexes:
            # Get the first selected index
            index = indexes[0]
            source_index = self.proxy_.mapToSource(index)
            tree = source_index.internalPointer()
            if tree:
                self.info_box_.update(tree.prop)
            else:
                self.info_box_.clear()
        else:
            self.info_box_.clear()

    def update_grabber(self, grabber: Optional[Grabber]):
        """Update grabber reference"""
        self.grabber_ = grabber
        self.delegate_.update_grabber(grabber)

    def update_model(self, cat: PropCategory):
        """Update with new property category"""
        # Close all editors first to ensure proper cleanup
        self._close_all_editors(self.proxy_, self.view_.rootIndex())

        # Remove model
        self.view_.setModel(None)

        # Create new model
        self.source_ = PropertyTreeModel(cat, self)
        self.proxy_.setSourceModel(self.source_)
        self.view_.setModel(self.proxy_)

        # Recreate editors
        if not self.settings_.show_root_item:
            root_index = self.proxy_.mapFromSource(self.source_.rootIndex())
            self.view_.setRootIndex(root_index)

        self._create_all_editors(self.proxy_, self.view_.rootIndex())
        self._update_visibility()

    def set_prop_visibility(self, visibility: PropertyVisibility):
        """Set visibility filter"""
        if self.visibility_combo_:
            # Find and set the matching item
            for i in range(self.visibility_combo_.count()):
                if self.visibility_combo_.itemData(i) == visibility:
                    self.visibility_combo_.setCurrentIndex(i)
                    break

    def set_filter_text(self, filter_text: str):
        """Set filter text"""
        if self.filter_text_:
            self.filter_text_.setText(filter_text)
