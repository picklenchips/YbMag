"""
Property tree model for displaying device properties
Translated from C++ PropertyTreeWidget.h/cpp
"""

from PyQt6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    Qt,
    QVariant,
    QSortFilterProxyModel,
    QRegularExpression,
)
from PyQt6.QtWidgets import QTreeView, QStyledItemDelegate, QWidget
from PyQt6.QtGui import QPainter
from typing import Optional, Callable, List
from weakref import ref

from imagingcontrol4.properties import (
    Property,
    PropertyType,
    PropCategory,
    PropertyVisibility,
)


class PropertyTreeNode:
    """Node in the property tree"""

    def __init__(
        self,
        parent,
        prop: Property,
        prop_type: PropertyType,
        row: int,
        prop_name: str,
        display_name: str,
    ):
        self.parent_ = parent
        self.prop_ = prop
        self.prop_type_ = prop_type
        self.row_ = row
        self.prop_name_ = prop_name
        self.display_name_ = display_name
        self.children_: List[PropertyTreeNode] = []
        self.notification_token_ = None
        self.prev_available_ = False

    def __del__(self):
        if self.notification_token_:
            try:
                self.prop_.event_remove_notification(self.notification_token_)
            except Exception:
                pass

    def populate(self):
        """Lazily populate children"""
        if self.children_:
            return

        if isinstance(self.prop_, PropCategory):
            try:
                index = 0
                # self.prop_ is already a PropCategory, don't call as_category()
                for feature in self.prop_.features:
                    try:
                        child_name = feature.name
                        child_display_name = feature.display_name
                        tmp_prop_type = feature.type

                        # Only show valid property types
                        if tmp_prop_type in [
                            PropertyType.INTEGER,
                            PropertyType.COMMAND,
                            PropertyType.STRING,
                            PropertyType.ENUMERATION,
                            PropertyType.BOOLEAN,
                            PropertyType.FLOAT,
                            PropertyType.CATEGORY,
                        ]:
                            child = PropertyTreeNode(
                                self,
                                feature,
                                tmp_prop_type,
                                index,
                                child_name,
                                child_display_name,
                            )
                            self.children_.append(child)
                            index += 1
                    except Exception as e:
                        pass
            except Exception as e:
                pass

    def num_children(self) -> int:
        """Get number of children"""
        self.populate()
        return len(self.children_)

    def child(self, n: int) -> Optional["PropertyTreeNode"]:
        """Get child at index"""
        self.populate()
        if 0 <= n < len(self.children_):
            return self.children_[n]
        return None

    def register_notification_once(
        self, item_changed: Callable[["PropertyTreeNode"], None]
    ):
        """Register notification handler once"""
        if self.notification_token_:
            return

        try:
            self.prev_available_ = self.prop_.is_available

            def notification_handler(prop):
                try:
                    new_available = prop.is_available()
                    if self.prev_available_ != new_available:
                        item_changed(self)
                        self.prev_available_ = new_available
                except Exception:
                    pass

            self.notification_token_ = self.prop_.event_add_notification(
                notification_handler
            )
        except Exception:
            pass

    def is_category(self) -> bool:
        """Check if node is a category"""
        return isinstance(self.prop_, PropCategory)

    @property
    def prop(self) -> Property:
        return self.prop_

    @property
    def children(self) -> List["PropertyTreeNode"]:
        return self.children_

    @property
    def row(self) -> int:
        return self.row_

    @property
    def parent(self):
        return self.parent_

    @property
    def display_name(self) -> str:
        return self.display_name_

    @property
    def prop_name(self) -> str:
        return self.prop_name_


class PropertyTreeModel(QAbstractItemModel):
    """Qt model for property tree"""

    def __init__(self, root: PropCategory, parent=None):
        super().__init__(parent)

        # Create tree root (dummy parent for actual root)
        self.tree_root_ = PropertyTreeNode(None, root, PropertyType.CATEGORY, 0, "", "")

        # Add actual root as child
        try:
            root_name = root.name
            root_display_name = root.display_name
            prop_root = PropertyTreeNode(
                self.tree_root_,
                root,
                PropertyType.CATEGORY,
                0,
                root_name,
                root_display_name,
            )
            self.tree_root_.children_.append(prop_root)
            self.prop_root_ = prop_root
        except Exception as e:
            print(f"Error creating property tree root: {e}")
            self.prop_root_ = None

    def rootIndex(self) -> QModelIndex:
        """Get index of root item"""
        if self.prop_root_:
            return self.createIndex(0, 0, self.prop_root_)
        return QModelIndex()

    def _parent_item(self, parent: QModelIndex) -> PropertyTreeNode:
        """Get parent item from index"""
        if not parent.isValid():
            return self.tree_root_
        return parent.internalPointer()

    def index(
        self, row: int, column: int, parent: QModelIndex = QModelIndex()
    ) -> QModelIndex:
        """Get index for row/column under parent"""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_item = self._parent_item(parent)
        child_item = parent_item.child(row)

        if child_item:
            # Register notification handler
            def item_changed(item):
                item_index = self.createIndex(item.row, 0, item)
                self.dataChanged.emit(item_index, item_index)

            child_item.register_notification_once(item_changed)
            return self.createIndex(row, column, child_item)

        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        """Get parent index"""
        if not index.isValid():
            return QModelIndex()

        child_item = index.internalPointer()
        parent_item = child_item.parent

        if parent_item == self.tree_root_:
            return QModelIndex()

        return self.createIndex(parent_item.row, 0, parent_item)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of rows under parent"""
        if parent.column() > 0:
            return 0

        parent_item = self._parent_item(parent)
        return parent_item.num_children()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Get number of columns"""
        return 2

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> QVariant:
        """Get data for index"""
        if not index.isValid():
            return QVariant()

        tree = index.internalPointer()

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if len(tree.children) == 0:
                return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight  # type: ignore
            else:
                return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft  # type: ignore

        elif role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return tree.display_name
            return QVariant()

        elif role == Qt.ItemDataRole.ToolTipRole:
            try:
                tt = tree.prop.tooltip
                if tt:
                    return tt
                desc = tree.prop.description
                if desc:
                    return desc
                return tree.display_name
            except Exception:
                return tree.display_name

        return QVariant()


class FilterPropertiesProxy(QSortFilterProxyModel):
    """Proxy model for filtering properties"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRecursiveFilteringEnabled(True)
        self.filter_regex_ = QRegularExpression("")
        self.visibility_ = PropertyVisibility.EXPERT
        self.filter_func_ = None

    def filter(self, text: str, vis: PropertyVisibility):
        """Set filter text and visibility"""
        self.filter_regex_ = QRegularExpression(
            text, QRegularExpression.PatternOption.CaseInsensitiveOption
        )
        self.visibility_ = vis
        self.invalidate()

    def filter_func(self, accept_prop: Callable[[Property], bool]):
        """Set custom filter function"""
        self.filter_func_ = accept_prop
        self.invalidate()

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Get item flags"""
        flags = super().flags(index)
        return flags & ~Qt.ItemFlag.ItemIsSelectable

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        """Check if row should be shown"""
        tree = source_parent.internalPointer()
        if not tree:
            return False

        if source_row >= len(tree.children):
            return False

        child = tree.children[source_row]

        # Hide all categories - Qt will show them if they have visible children
        if child.is_category():
            return False

        try:
            if not child.prop.is_available:
                return False

            if child.prop.visibility > self.visibility_:
                return False

            # Check text filter
            if not (
                self.filter_regex_.match(child.display_name).hasMatch()
                or self.filter_regex_.match(child.prop_name).hasMatch()
            ):
                return False

            # Check custom filter
            if self.filter_func_:
                return self.filter_func_(child.prop)

            return True
        except Exception as e:
            print(f"[filterAcceptsRow] error for {child.display_name}: {e}")
            import traceback

            traceback.print_exc()
            return False
