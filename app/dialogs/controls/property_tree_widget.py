"""
Property tree widget
Translated from C++ PropertyTreeWidget.h/cpp
"""

from PyQt6.QtCore import Qt, QRect, QModelIndex, QItemSelection
from PyQt6.QtWidgets import (
    QWidget,
    QTreeView,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QFrame,
    QStyledItemDelegate,
    QSplitter,
    QAbstractItemView,
    QHeaderView,
)
from PyQt6.QtGui import QPainter, QMouseEvent, QShortcut, QKeySequence, QPalette
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


# Style matching C++ CustomStyle.PropertyTreeViewStyle
PROPERTY_TREE_VIEW_STYLE = (
    "QTreeView::branch, QTreeView::item, QTreeView { "
    "outline: none; "
    "show-decoration-selected: 0;"
    "color: palette(text);"
    "background: palette(window);"
    "font-size: 13px;"
    "}"
    "QTreeView::branch:open:adjoins-item:has-children{"
    "background: transparent;"
    "margin : 0;"
    " }"
    "QTreeView::branch:closed:adjoins-item:has-children{"
    "background: transparent;"
    "margin : 0;"
    " }"
)


class PropertyTreeItemDelegate(QStyledItemDelegate):
    """Delegate for creating editors in the tree (column 1)"""

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

    def paint(self, painter: QPainter, option, index):
        """Paint category rows with grey background to match column 0"""
        source_index = self.proxy_.mapToSource(index)
        tree = source_index.internalPointer()
        if tree and len(tree.children) > 0:
            painter.save()
            widget = option.widget
            if widget:
                painter.fillRect(option.rect, widget.palette().mid())
            painter.restore()
        else:
            super().paint(painter, option, index)

    def updateEditorGeometry(self, editor, option, index):
        """Ensure editor fills the full cell rect"""
        assert editor is not None, "Editor widget is None in updateEditorGeometry"
        editor.setGeometry(option.rect)

    def createEditor(self, parent: QWidget, option, index) -> Optional[QWidget]:
        """Create editor widget for property"""
        source_index = self.proxy_.mapToSource(index)
        tree = source_index.internalPointer()

        if not tree or len(tree.children) > 0:
            return None  # No editor for categories; paint() handles their background

        try:
            widget = create_prop_control(
                tree.prop,
                parent,
                self.grabber_,
                self.restart_filter_,
                self.prop_selected_,
            )

            if widget:
                widget.setContentsMargins(0, 0, 8, 0)  # Match C++ right margin
            else:
                # Log when no widget was created
                prop_name = "<unknown>"
                try:
                    prop_name = (
                        tree.prop.name if hasattr(tree.prop, "name") else "<no name>"
                    )
                except Exception:
                    pass
                print(f"Debug: No editor widget created for property '{prop_name}'")

            return widget
        except Exception as e:
            prop_name = "<unknown>"
            try:
                prop_name = (
                    tree.prop.name if hasattr(tree.prop, "name") else "<no name>"
                )
            except Exception:
                pass
            print(
                f"Error: Exception in createEditor for property '{prop_name}': {type(e).__name__}: {e}"
            )
            return None


class TestItemDelegateForPaint(QStyledItemDelegate):
    """Delegate for painting category names in column 0
    Matches C++ TestItemDelegateForPaint"""

    def __init__(self, proxy: FilterPropertiesProxy, parent: QWidget):
        super().__init__(parent)
        self.proxy_ = proxy
        self.parent_ = parent

    def paint(self, painter: QPainter, option, index):
        """Custom painting for categories"""
        source_index = self.proxy_.mapToSource(index)
        tree = source_index.internalPointer()

        if tree and len(tree.children) > 0:
            # Paint category row with category background/text
            painter.save()
            painter.setPen(self.parent_.palette().color(QPalette.ColorRole.Text))
            r = option.rect
            painter.fillRect(r, self.parent_.palette().mid())
            painter.drawText(r, option.displayAlignment, index.data())
            painter.restore()
        else:
            super().paint(painter, option, index)


class PropertyTreeView(QTreeView):
    """Custom tree view for properties"""

    def __init__(self, proxy: FilterPropertiesProxy):
        super().__init__()
        self.proxy_ = proxy

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press to toggle expansion for category rows.

        Only toggle when clicking on column 0 or on category rows (which have
        no persistent editor in column 1).  Clicks on column-1 leaf rows must
        pass through to the persistent editor widget.
        """
        index = self.indexAt(event.pos())
        if not index.isValid():
            super().mousePressEvent(event)
            return

        source_index = self.proxy_.mapToSource(index)
        tree = source_index.internalPointer()
        is_category = tree and len(tree.children) > 0

        last_state = self.isExpanded(index)
        super().mousePressEvent(event)

        # Only toggle expand/collapse for category rows
        if is_category and last_state == self.isExpanded(index):
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


@dataclass
class PropertyTreeWidgetSettings:
    """Settings for property tree widget"""

    show_root_item: bool = False
    show_info_box: bool = True
    show_filter: bool = True
    initial_filter: str = ""
    stream_restart_filter: Optional[StreamRestartFilterFunction] = None


class PropertyTreeWidget(QWidget):
    """Main property tree widget
    Matches C++ PropertyTreeWidgetBase<QWidget>"""

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

        # Create model
        self.source_ = PropertyTreeModel(cat, self)

        # Create proxy
        self.proxy_ = FilterPropertiesProxy(self)

        # Create info box early (needed for prop_selected callback in delegate)
        self.info_text_ = None
        if settings.show_info_box:
            self.info_text_ = PropertyInfoBox(self)

        # Create delegates
        prop_selected_func = lambda prop: (
            self.info_text_.update(prop) if self.info_text_ else None
        )
        self.delegate_ = PropertyTreeItemDelegate(
            self.proxy_, grabber, settings.stream_restart_filter, prop_selected_func
        )
        self.branch_paint_delegate_ = TestItemDelegateForPaint(self.proxy_, self)

        # Build UI inside a QFrame (matches C++ pattern)
        frame = QFrame(self)
        layout = QVBoxLayout(frame)

        # Filter
        self.filter_text_ = None

        if settings.show_filter:
            top = QHBoxLayout()

            self.filter_text_ = QLineEdit()
            self.filter_text_.setStyleSheet("QLineEdit { font-size: 13px; }")
            self.filter_text_.setText(settings.initial_filter)
            self.filter_text_.setPlaceholderText("Search Properties (Ctrl-F)")
            self.filter_text_.setClearButtonEnabled(True)

            search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
            search_shortcut.activated.connect(
                lambda: (
                    self.filter_text_.setFocus(Qt.FocusReason.ShortcutFocusReason)
                    if self.filter_text_
                    else None
                )
            )

            self.filter_text_.textChanged.connect(lambda _: self._update_filter())
            top.addWidget(self.filter_text_)

            layout.addLayout(top)
            self._update_filter()

        # Create tree view
        self.view_ = PropertyTreeView(self.proxy_)
        self.view_.setStyleSheet(PROPERTY_TREE_VIEW_STYLE)
        self.proxy_.setSourceModel(self.source_)
        self.proxy_.filter(settings.initial_filter, PropertyVisibility.GURU)

        self.view_.setModel(self.proxy_)
        self.view_.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        if header := self.view_.header():
            header.setHidden(True)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setStretchLastSection(True)
        self.view_.setItemDelegateForColumn(0, self.branch_paint_delegate_)
        self.view_.setItemDelegateForColumn(1, self.delegate_)

        # Connect signals
        self.view_.clicked.connect(self._prop_selected)
        if sel_model := self.view_.selectionModel():
            sel_model.selectionChanged.connect(self._prop_selection_changed)
        self.proxy_.layoutChanged.connect(self._proxy_layout_changed)

        # Layout: splitter or just tree
        if settings.show_info_box and self.info_text_:
            splitter = QSplitter(Qt.Orientation.Vertical, self)
            layout.addWidget(splitter)
            splitter.addWidget(self.view_)
            splitter.addWidget(self.info_text_)
            splitter.setStretchFactor(0, 3)
        else:
            layout.addWidget(self.view_)

        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        frame.setLayout(layout)

        # For QWidget base, set frame's layout as our layout
        self.setLayout(layout)

        # Initial view setup
        self._update_view()

    # -- Private helpers matching C++ --

    def _update_filter(self):
        """Read filter text and update proxy"""
        text = self.filter_text_.text() if self.filter_text_ else ""
        self.proxy_.filter(text, PropertyVisibility.GURU)

    def _create_all_editors(self, model, parent: QModelIndex):
        """Recursively open persistent editors on column 1 for all rows"""
        rows = model.rowCount(parent)
        for row in range(rows):
            index1 = model.index(row, 1, parent)
            self.view_.openPersistentEditor(index1)

            index0 = model.index(row, 0, parent)
            self._create_all_editors(model, index0)

    def _prop_selection_changed(
        self, selected: QItemSelection, deselected: QItemSelection
    ):
        """Handle selection change for info box"""
        if not selected.isEmpty() and len(selected) > 0 and not selected[0].isEmpty():
            item = selected[0].indexes()[0]
            self._prop_selected(item)
        else:
            self._prop_selected(QModelIndex())

    def _prop_selected(self, index: QModelIndex):
        """Update info box from selected index"""
        if not self.info_text_:
            return

        source_index = self.proxy_.mapToSource(index)
        tree = source_index.internalPointer()
        if not tree:
            self.info_text_.clear()
            return

        self.info_text_.update(tree.prop)

    def _update_view(self):
        """Refresh the tree: set root, create editors, expand, configure header"""
        if not self.settings_.show_root_item and self.source_:
            self.view_.setRootIndex(self.proxy_.mapFromSource(self.source_.rootIndex()))

        self._create_all_editors(self.proxy_, self.view_.rootIndex())
        self.view_.expandAll()

        source_available = self.source_ is not None

        if self.info_text_:
            self.info_text_.setEnabled(source_available)
        if self.filter_text_:
            self.filter_text_.setEnabled(source_available)
        self.view_.setEnabled(source_available)

        if source_available:
            self.view_.resizeColumnToContents(0)

    def _proxy_layout_changed(self, *args):
        self._update_view()

    # -- Public API matching C++ --

    def clear_model(self):
        """Clear the model (set to None)"""
        self._update_model_internal(None)

    def update_model(self, cat: PropCategory):
        """Update with a new property category"""
        self._update_model_internal(PropertyTreeModel(cat, self))

    def _update_model_internal(self, model: Optional[PropertyTreeModel]):
        """Replace the source model"""
        # Close persistent editors first so their Property / QModelIndex refs
        # are released before the model is swapped out.
        self._close_all_editors(self.proxy_, self.view_.rootIndex())

        old_model = self.source_
        self.source_ = model
        self.proxy_.setSourceModel(self.source_)
        self._update_view()

        # Explicitly clear old model to break parent<->children reference
        # cycles in PropertyTreeNode and release IC4 property handles.
        if old_model is not None:
            old_model.clear()

    def update_grabber(self, grabber: Optional[Grabber]):
        """Update with a new grabber - matches C++ updateGrabber"""
        if not grabber:
            self.clear_model()
            return
        try:
            prop_map = grabber.device_property_map
            cat = prop_map.find_category("Root")
            self.delegate_.update_grabber(grabber)
            self._update_model_internal(PropertyTreeModel(cat, self))
        except Exception:
            pass

    def set_property_filter(self, accept_prop: Callable):
        """Set a custom filter function"""
        self.proxy_.filter_func(accept_prop)

    def set_filter_text(self, filter_text: str):
        """Set filter text"""
        if self.filter_text_:
            self.filter_text_.setText(filter_text)
            self._update_filter()

    def _close_all_editors(self, model, parent: QModelIndex):
        """Recursively close persistent editors on column 1 for all rows"""
        rows = model.rowCount(parent)
        for row in range(rows):
            index1 = model.index(row, 1, parent)
            self.view_.closePersistentEditor(index1)

            index0 = model.index(row, 0, parent)
            self._close_all_editors(model, index0)

    def closeEvent(self, event):
        """Clean up when widget is closed"""
        self.clear_model()
        super().closeEvent(event)
