"""
Tabbed property widget – properties organized in category tabs with
global search, match highlighting, and a shared info box.
"""

from PyQt6.QtCore import Qt, QModelIndex, QItemSelection, QRegularExpression
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QTabWidget,
    QSplitter,
    QAbstractItemView,
    QAbstractScrollArea,
    QHeaderView,
)
from PyQt6.QtGui import QPainter, QShortcut, QKeySequence, QPalette, QColor
from imagingcontrol4.properties import (
    PropertyVisibility,
    PropCategory,
    PropertyMap,
    PropertyType,
)
from imagingcontrol4.grabber import Grabber
from typing import Optional, Dict, List
from dataclasses import dataclass

from .property_tree_model import (
    PropertyTreeModel,
    FilterPropertiesProxy,
    PropertyTreeNode,
)
from .property_tree_widget import (
    PropertyTreeView,
    PropertyTreeItemDelegate,
    TestItemDelegateForPaint,
    PROPERTY_TREE_VIEW_STYLE,
)
from .props.prop_control_base import StreamRestartFilterFunction
from .property_info_box import PropertyInfoBox


# Semi-transparent orange overlay for search-match highlighting
HIGHLIGHT_COLOR = QColor(255, 170, 0, 80)


class _HighlightDelegate(TestItemDelegateForPaint):
    """Column-0 delegate that overlays a highlight on search-matched properties."""

    def __init__(self, proxy: FilterPropertiesProxy, parent: QWidget):
        super().__init__(proxy, parent)
        self._highlight_regex: Optional[QRegularExpression] = None

    def set_highlight(self, text: str):
        """Set (or clear) the search highlight text."""
        self._highlight_regex = (
            QRegularExpression(
                text, QRegularExpression.PatternOption.CaseInsensitiveOption
            )
            if text
            else None
        )

    def paint(self, painter: QPainter, option, index):
        # Normal category / property painting first
        super().paint(painter, option, index)

        if not self._highlight_regex:
            return

        source = self.proxy_.mapToSource(index)
        node = source.internalPointer()
        if node and len(node.children) == 0:
            if (
                self._highlight_regex.match(node.display_name).hasMatch()
                or self._highlight_regex.match(node.prop_name).hasMatch()
            ):
                painter.fillRect(option.rect, HIGHLIGHT_COLOR)


@dataclass
class _TabInfo:
    """Internal bookkeeping for a single category tab."""

    name: str
    category: PropCategory
    model: Optional[PropertyTreeModel]
    proxy: FilterPropertiesProxy
    view: PropertyTreeView
    editor_delegate: PropertyTreeItemDelegate
    paint_delegate: _HighlightDelegate
    is_additional: bool = False


class TabbedPropertyWidget(QWidget):
    """Property browser: category tabs, global search, shared info box.

    Top-level categories from the property map each become a tab.
    Additional property maps (e.g. codec settings) get their own tabs.
    A search bar above the tabs hides non-matching tabs and highlights
    matching property names within visible tabs.
    """

    def __init__(
        self,
        property_map: PropertyMap,
        grabber: Optional[Grabber] = None,
        additional_maps: Optional[Dict[str, PropertyMap]] = None,
        stream_restart_filter: Optional[StreamRestartFilterFunction] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._grabber = grabber
        self._property_map = property_map
        self._additional_maps = additional_maps or {}
        self._restart_filter = stream_restart_filter
        self._tabs: List[_TabInfo] = []

        self._build_ui()
        self._populate_tabs()

    # ── UI construction ──────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(4)

        # Global search box
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search Properties (Ctrl+F)")
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet("QLineEdit { font-size: 13px; padding: 4px; }")
        self._search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search)

        QShortcut(QKeySequence.StandardKey.Find, self).activated.connect(
            lambda: self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        )

        # Splitter: tabs above, info box below
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._tab_widget = QTabWidget()
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        splitter.addWidget(self._tab_widget)

        self._info_box = PropertyInfoBox(self)
        splitter.addWidget(self._info_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    # ── Tab management ───────────────────────────────────────────

    def _populate_tabs(self):
        """Build category tabs from the current property map."""
        self._clear_tabs()

        try:
            root = self._property_map.find_category("Root")
        except Exception:
            return

        # Collect top-level sub-categories
        categories: List[PropCategory] = []
        try:
            for feat in root.features:
                if isinstance(feat, PropCategory):
                    categories.append(feat)
        except Exception:
            pass

        if categories:
            for cat in categories:
                self._add_tab(cat.display_name, cat)
        else:
            # No sub-categories – show root directly
            self._add_tab("Properties", root)

        # Additional property maps (e.g. codec settings)
        for map_name, pmap in self._additional_maps.items():
            try:
                self._add_tab(map_name, pmap.find_category("Root"), is_additional=True)
            except Exception:
                pass

    def _add_tab(
        self,
        name: str,
        category: PropCategory,
        is_additional: bool = False,
    ):
        """Create model / proxy / view / delegates and register a tab."""
        grabber = None if is_additional else self._grabber

        model = PropertyTreeModel(category, self)
        proxy = FilterPropertiesProxy(self)
        proxy.setSourceModel(model)
        proxy.filter("", PropertyVisibility.GURU)

        # Shared info-box callback
        prop_selected = lambda prop: self._info_box.update(prop)

        editor_del = PropertyTreeItemDelegate(
            proxy, grabber, self._restart_filter, prop_selected
        )
        paint_del = _HighlightDelegate(proxy, self)

        view = PropertyTreeView(proxy)
        view.setStyleSheet(PROPERTY_TREE_VIEW_STYLE)
        view.setModel(proxy)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        if hdr := view.header():
            hdr.setHidden(True)
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hdr.setStretchLastSection(True)

        view.setItemDelegateForColumn(0, paint_del)
        view.setItemDelegateForColumn(1, editor_del)

        # Set uniform row height to accommodate editors
        # Delegate's sizeHint() will determine the actual row height
        view.setUniformRowHeights(True)

        # Show children of the category (skip root wrapper node)
        root_idx = model.rootIndex()
        if root_idx.isValid():
            view.setRootIndex(proxy.mapFromSource(root_idx))

        self._open_editors(view, proxy, view.rootIndex())
        view.expandAll()

        # Selection → info box
        view.clicked.connect(lambda idx, p=proxy: self._show_info(p, idx))
        if sel := view.selectionModel():
            sel.selectionChanged.connect(
                lambda s, _d, p=proxy: (
                    self._show_info(p, s[0].indexes()[0])
                    if not s.isEmpty() and s[0].indexes()
                    else None
                )
            )

        # Model changes → refresh that tab's view
        proxy.dataChanged.connect(
            lambda *_a, v=view, p=proxy, m=model: self._refresh_view(v, p, m)
        )
        proxy.layoutChanged.connect(
            lambda *_a, v=view, p=proxy, m=model: self._refresh_view(v, p, m)
        )

        self._tab_widget.addTab(view, name)
        self._tabs.append(
            _TabInfo(
                name=name,
                category=category,
                model=model,
                proxy=proxy,
                view=view,
                editor_delegate=editor_del,
                paint_delegate=paint_del,
                is_additional=is_additional,
            )
        )

    def _clear_tabs(self):
        """Remove all tabs and release models."""
        # Disconnect signals first to avoid dangling callbacks
        for tab in self._tabs:
            try:
                tab.proxy.dataChanged.disconnect()
                tab.proxy.layoutChanged.disconnect()
            except Exception:
                pass
            tab.proxy.setSourceModel(None)
            # Explicitly break node reference cycles so IC4 handles are freed
            if tab.model is not None:
                tab.model.clear()
            tab.model = None

        while self._tab_widget.count():
            w = self._tab_widget.widget(0)
            self._tab_widget.removeTab(0)
            if w:
                w.deleteLater()

        self._tabs.clear()
        # Release references to additional PropertyMap objects so they can be
        # garbage collected before the IC4 Library context is torn down
        self._additional_maps.clear()

    def _refresh_view(self, view, proxy, model):
        """Re-setup a tab's view after model data/layout change."""
        root_idx = model.rootIndex() if model else QModelIndex()
        if root_idx.isValid():
            view.setRootIndex(proxy.mapFromSource(root_idx))
        self._open_editors(view, proxy, view.rootIndex())
        view.expandAll()

    @staticmethod
    def _open_editors(view, proxy, parent: QModelIndex):
        """Recursively open persistent editors on column 1."""
        for row in range(proxy.rowCount(parent)):
            view.openPersistentEditor(proxy.index(row, 1, parent))
            TabbedPropertyWidget._open_editors(view, proxy, proxy.index(row, 0, parent))

    # ── Search & highlight ───────────────────────────────────────

    def _on_search_changed(self, text: str):
        """Update tab visibility and highlights in response to search input."""
        text = text.strip()
        regex = (
            QRegularExpression(
                text, QRegularExpression.PatternOption.CaseInsensitiveOption
            )
            if text
            else None
        )

        first_visible = -1
        for i, tab in enumerate(self._tabs):
            tab.paint_delegate.set_highlight(text)

            if not regex:
                visible = True
            elif tab.model and tab.model.prop_root_:
                visible = self._node_matches(tab.model.prop_root_, regex)
            else:
                visible = False

            self._tab_widget.setTabVisible(i, visible)

            if visible:
                vp = tab.view.viewport()
                if vp:
                    vp.update()
                if first_visible < 0:
                    first_visible = i

        # If the current tab became hidden, switch to the first visible one
        cur = self._tab_widget.currentIndex()
        if cur >= 0 and not self._tab_widget.isTabVisible(cur) and first_visible >= 0:
            self._tab_widget.setCurrentIndex(first_visible)

    @staticmethod
    def _node_matches(
        node: Optional[PropertyTreeNode], regex: QRegularExpression
    ) -> bool:
        """Recursively check whether any available property under *node* matches."""
        if node is None:
            return False
        node.populate()
        for child in node.children:
            if child.is_category():
                if TabbedPropertyWidget._node_matches(child, regex):
                    return True
            else:
                try:
                    if not child.prop.is_available:
                        continue
                    if (
                        regex.match(child.display_name).hasMatch()
                        or regex.match(child.prop_name).hasMatch()
                    ):
                        return True
                except Exception:
                    pass
        return False

    # ── Selection → info box ─────────────────────────────────────

    def _on_tab_changed(self, index: int):
        """Repaint the newly-visible tab so highlights are current."""
        if 0 <= index < self._tab_widget.count():
            w = self._tab_widget.widget(index)
            if isinstance(w, QAbstractScrollArea):
                vp = w.viewport()
                if vp:
                    vp.update()

    def _show_info(self, proxy, index: QModelIndex):
        source = proxy.mapToSource(index)
        node = source.internalPointer()
        if node:
            self._info_box.update(node.prop)
        else:
            self._info_box.clear()

    # ── Public API ───────────────────────────────────────────────

    def update_grabber(self, grabber: Grabber):
        """Rebuild tabs after a device change."""
        self._grabber = grabber
        self._property_map = grabber.device_property_map
        self._populate_tabs()

    def clear_all(self):
        """Drop all models – call before closing the device."""
        self._clear_tabs()

    def set_filter_text(self, text: str):
        """Programmatically set the search text."""
        self._search.setText(text)
