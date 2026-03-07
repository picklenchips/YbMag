# Property Tree Issues: Root Cause Analysis

**UPDATE (Current Status)**: Code has been improved since initial analysis. Many suspected issues (A1, A2, A4) are NOT present in current code.

Two observed problems: (A) editor widgets in column 1 don't stretch to fill the full column width, and (B) enumeration controls (combo boxes) don't fill visible values and are non-interactive. 

## Confirmed User Observations (2026-03-06 - Testing):

### Problem A: Column Width & Stretching
1. ❌ **Right column of category can be opened (clickable when closed) but not closed (not clickable when open)**
   - Clicking on column 1 (right side) of a category row opens it
   - Clicking on it again does NOT close it
   - **Implication**: Column 1 is receiving the click event correctly for expand, but tree view's mousePressEvent may not be routing the second click properly

2. ❌ **Enumeration control widget width is LARGER than other control widget widths**
   - `QComboBox` used for enum controls displays wider than `QLineEdit` or spin boxes
   - Other controls are narrower and NOT filling column width
   - **Implication**: Controls have mismatched size policies or the combo box has larger minimum width

3. ❌ **None of the control widget widths are correctly stretching to fully cover the column width**
   - Even on minimally-sized window, editors leave gaps in column 1
   - All control types (enum, string, integer, boolean) show this behavior
   - **Implication**: This is NOT enumeration-specific; it's a systemic layout issue with PropControlBase or the tree view itself

### Problem B: Enumeration Value Display
4. ❌ **Enumeration control is broken - can't see the value**
   - The combo box exists and appears to have entries
   - BUT the selected/current value is NOT VISIBLE
   - **Implication**: Value is being read but not displayed in the combo, OR combo is configured to hide the selected item

---

## Current Code Status vs. Original Analysis

### Issues Already Fixed (NOT in current code):
- ✅ **A1**: `sizeHint` returning `QSize(0, 48)` — **NOT PRESENT** in current code
- ✅ **A2**: `setUniformRowHeights(True)` — **NOT PRESENT** in current code  
- ✅ **A4**: `_update_view()` fires on every `dataChanged` — **NOT PRESENT** (only connected to `layoutChanged`)
- ✅ **B1**: Editor recreation on dataChanged — **NOT AN ISSUE** (dataChanged not connected)

### Improvements Added (2026-03-06):
- ✅ **B2**: Added comprehensive error logging to `create_prop_control()` and `createEditor()`
  - Now logs property name, type, and exception details when control creation fails
- ✅ Added debug logging to `filterAcceptsRow()` for enumeration properties
  - Logs availability, visibility, and filter match status
- ✅ Added exception logging in `filterAcceptsRow()` to catch filtering errors

---

## Problem A: Column Width & Stretching

### NEW ANALYSIS (2026-03-06):

**Key Finding**: Controls have mismatched widths, and NONE are stretching to fill column 1. Enumerations are WIDER than other controls.

#### Root Cause Identified: QComboBox Minimum Width vs. QLineEdit

In [prop_enumeration_control.py](../app/dialogs/controls/props/prop_enumeration_control.py):
```python
self.combo.setMinimumWidth(150)  # <-- EXPLICIT MINIMUM WIDTH!
```

Other controls (PropStringControl, PropIntegerControl) use default `QLineEdit` width (typically ~60-100px), but the combo explicitly sets 150px minimum.

**This explains observation #2**: The enum combo appears wider because it IS wider (150px minimum) vs default edit boxes.

**This explains observation #3**: Even with `Expanding` size policy, controls can't stretch below their minimum width. So:
- Edit boxes sit at ~80px (their natural minimum)
- Combo sits at 150px (forced minimum)
- Layout calculates parent `PropControlBase` size based on child minimums
- Tree view sizes `PropControlBase` to fit children, NOT to fill column 1
- Result: Column 1 has gaps

#### The Real Problem: Layout Sizing Order Is Backwards

Qt persistent editors work like this:
1. **Delegate's `sizeHint()`** tells Qt how big to make the cell for initial layout
2. **Tree view sizes column** based on header policy (`Stretch`) and available space
3. **`updateEditorGeometry(option.rect)`** is called with the column's final rect
4. **Editor widget is sized** to fill `option.rect`
5. **Children inside editor** should fill available space if they have `Expanding` policy

**But in current code**:
- Step 1: No `sizeHint()` override, so Qt uses default (probably 0 or very small)
- Step 2: Column headers are set to `Stretch`, but if all children have natural minimum, column might not grow
- Step 3-5: Editor gets sized to `option.rect`, but children inside use their minimum widths
- **Result**: Editor fills column, but children don't fill editor

**Key Issue**: `PropControlBase`'s layout has children with stretch factors ≥1, but if the parent `PropControlBase` is sized to fit ALL children's minimums, the children can't stretch past the parent's size.

### Refined Causes:

#### A-Width-1: QComboBox Explicit `setMinimumWidth(150)`
**Impact: HIGH** — The 150px minimum is hardcoded and not justified. Other controls don't set explicit minimums. Remove this line and let QComboBox use its natural minimum.

**Fix**: In [prop_enumeration_control.py](../app/dialogs/controls/props/prop_enumeration_control.py), remove:
```python
self.combo.setMinimumWidth(150)  # DELETE THIS LINE
```

#### A-Width-2: No Delegate `sizeHint()` Guidance for Column Sizing
**Impact: MEDIUM** — Without `sizeHint()`, Qt doesn't know the preferred cell size, so persistent editor layout can be suboptimal. The C++ code doesn't override `sizeHint()` either, but it probably relies on default Qt behavior that matches better.

**Fix**: Add `sizeHint()` to delegates that returns `QSize(option.rect.width(), 48)` or `QSize(-1, 48)` to signal "stretch to available width, fixed height 48".

#### A-Width-3: `PropControlBase` Layout Not Respecting Parent Geometry
**Impact: MEDIUM** — `PropControlBase.setGeometry(rect)` is called by `updateEditorGeometry`, but the internal `QHBoxLayout` might not be updating children to fill the new geometry immediately. Qt layouts can have timing issues with persistent editors.

**Fix**: Override `resizeEvent()` in `PropControlBase` to explicitly trigger layout recalculation when editor is resized.

---

## Problem B-1: Category Row Click Behavior (Right Column Toggle Not Working)

### NEW ANALYSIS (2026-03-06):

**Observation**: Right column (column 1) of category rows can open expansion when clicked, but cannot close it.

#### Root Cause: `PropertyTreeView.mousePressEvent()` Logic

Current code in [property_tree_widget.py](../app/dialogs/controls/property_tree_widget.py):
```python
is_category = tree and len(tree.children) > 0

last_state = self.isExpanded(index)
super().mousePressEvent(event)  # <-- Tree processes click here

# Only toggle expand/collapse for category rows
if is_category and last_state == self.isExpanded(index):
    self.setExpanded(index, not last_state)  # Toggle only if state didn't change
```

**Problem**: 
- `super().mousePressEvent(event)` might be toggling the category row already
- Then the `if` check sees that state HAS changed and DOESN'T toggle again (if `is_category and last_state == self.isExpanded(index)` is False after super() changes it)
- Result: Single click closes, but single click doesn't open (or vice versa)

**The logic is**: "Only toggle again if state is the same after super() processes it"
- **First click**: `last_state = False`, super() toggles to True, check is False, NO second toggle → stays True ✓
- **Second click**: `last_state = True`, super() toggles to False, check is False, NO second toggle → stays False ✓

Wait, that logic should work both ways. Let me reconsider...

Actually, the issue might be that **super().mousePressEvent() is NOT toggling** in some cases. Or the click is being processed by the persistent editor in column 1, not the category row itself.

**For category rows**: column 0 has the category text, column 1 should be empty (no persistent editor)
- If you click column 0: Should get the category expand logic
- If you click column 1 of a category: Currently might be hitting different code path

The `mousePressEvent` checks `index.column()` implicitly by using the index from `indexAt()`. If clicking column 1 of a category, it should still be the same logical row but different column.

**Actual Issue**: The check `if is_category and last_state == self.isExpanded(index)` is **inverted logic**. 
- It says "toggle IF state didn't change"
- But super() doesn't always change state (super() just forwards to parent's mousePressEvent, which might not toggle)
- So this logic is: "toggle manually to force a toggle if super didn't toggle"
- But this only works if super() always toggles or always doesn't toggle consistently

**Fix**: Simplify the logic. For categories, always toggle expansion when clicked, regardless of what super() did:
```python
last_state = self.isExpanded(index)
super().mousePressEvent(event)

if is_category:
    # Force toggle for categories with different column click handling
    self.setExpanded(index, not last_state)
```

---

## Problem B-2: Enumeration Value Not Visible

### NEW ANALYSIS (2026-03-06):

**Observation**: Combo box exists and dropdown works, but the **current/selected value is not displayed** in the combo box display area.

#### Possible Root Causes:

##### B2-Visible-1: Combo Box Text Color Matches Background
**Impact: HIGH** — If the text color is set to match the background (or is transparent), the text would be invisible even though it's in the combo.

**Check**: In [prop_enumeration_control.py](../app/dialogs/controls/props/prop_enumeration_control.py), look for:
```python
self.combo.setForeground()  # or similar color setting
```

Or the theme stylesheet might be setting text color to transparent or white-on-white.

##### B2-Visible-2: Combo Box Height Too Small to Display Text
**Impact: MEDIUM** — If the combo height is less than the text font height + margins, text gets clipped vertically.

Currently in code: `self.combo.setMinimumHeight(28)` with font size 13px should fit, but padding might be eating space.

##### B2-Visible-3: Text Is Being Set to Empty String
**Impact: HIGH** — In `update_all()`, the current value might not be matching any entry in the combo (due to type mismatch, rounding, etc.), so `currentIndex` stays at -1 or 0 with empty text.

##### B2-Visible-4: ComboBox has `editable=False` AND No Display Text Formatting
**Impact: MEDIUM** — When a combo box is read-only and an item is selected, Qt automatically shows the item's text. But if the selected index is -1 or if the item's `text` role is empty, nothing displays.

---

### Refined Causes for Problem B (Enumeration):

#### B-Display-1: Enumeration Entry Text Might Be Empty
In [prop_enumeration_control.py](../app/dialogs/controls/props/prop_enumeration_control.py#L109-L125):
```python
# Get display name safely
try:
    name = entry.display_name
except Exception:
    try:
        name = entry.name
    except Exception:
        name = ""

if not name or name.strip() == "":
    # Skip entries with empty display names
    continue
```

**Issue**: If all valid entries have empty display names, combo might end up with no items or with fallback items. If `current_value` doesn't match any entry value (due to type conversion or API mismatch), selectedIndex stays at -1 and no text displays.

**Fix**: Debug log which entries are being added vs. skipped. Add logging:
```python
print(f"Enum entry: name='{name}', value={val}, matches_current={val == current_value}")
```

#### B-Display-2: Current Value Type Mismatch
**Impact: HIGH** — `current_value = self.prop.int_value` gets an integer, but entries might have string values or different numeric types. The comparison `val == current_value` fails silently, so no index is set.

**The code does try to match by value**:
```python
if (
    not current_index_set
    and current_value is not None
    and val == current_value
):
    self.combo.setCurrentIndex(self.combo.count() - 1)
    current_index_set = True
```

But if this comparison always fails (type mismatch), `current_index_set` stays False. Then:
```python
if not current_index_set and self.combo.count() > 0:
    self.combo.setCurrentIndex(0)
```

Sets index to 0, which should display the first entry's text. Unless... the first entry is also skipped somehow.

**Fix**: Add debug logging to see if entries are being added and if current index is being set correctly.

---

## Recommended Fixes (Priority Order):

### IMMEDIATE (Fixes Known Issues):

1. **Remove `setMinimumWidth(150)` from QComboBox** (A-Width-1)
   - File: [prop_enumeration_control.py](../app/dialogs/controls/props/prop_enumeration_control.py)
   - Current: `self.combo.setMinimumWidth(150)`
   - Action: Delete this line
   - **Expected Impact**: Combo will size like other controls, all controls will better stretch to column width

2. **Add `sizeHint()` override to delegate** (A-Width-2)
   - File: [property_tree_widget.py](../app/dialogs/controls/controls/property_tree_widget.py)
   - Class: `PropertyTreeItemDelegate`
   - Action: Override `sizeHint` to return width hint matching available space
   - **Expected Impact**: Tree view will allocate column width correctly for editors

3. **Fix category row toggle logic** (B-1)
   - File: [property_tree_widget.py](../app/dialogs/controls/property_tree_widget.py)
   - Method: `PropertyTreeView.mousePressEvent()`
   - Current logic seems inverted or inconsistent
   - Action: Simplify to always toggle for categories
   - **Expected Impact**: Right-click on category row will both open and close

### HIGH PRIORITY (Diagnose Enum Value Display):

4. **Add value matching debug logging** (B-Display-2)
   - File: [prop_enumeration_control.py](../app/dialogs/controls/props/prop_enumeration_control.py)
   - Method: `update_all()`
   - Action: Log each entry's name, value, and whether it matches current value
   - **Expected Impact**: Console will show why value isn't matching/displaying

---

### Confirmed Settings (Should Be Correct)
- Header: both columns set to `QHeaderView.ResizeMode.Stretch`
- `setStretchLastSection(True)` enabled
- `PropControlBase` sets `QSizePolicy(Expanding, Expanding)` on itself
- Individual controls (combo, spin, edit) have stretch factors ≥1 in their layouts

### DEPRECATED Sections (No Longer Relevant):

#### ~~A1. `sizeHint` Returning `QSize(0, 48)` — Width of 0~~
**NOT PRESENT** — Delegates don't override `sizeHint()`

#### ~~A2. `setUniformRowHeights(True)` Interaction with Persistent Editors~~
**NOT PRESENT** — This was removed in previous fixes

#### ~~A4. `_update_view()` Fires on Every `dataChanged` / `layoutChanged`~~
**NOT AN ISSUE** — Only connected to `layoutChanged`, not `dataChanged`

#### A4. `_update_view()` Fires on Every `dataChanged` / `layoutChanged`
**Impact: MEDIUM** — `_proxy_data_changed` and `_proxy_layout_changed` both call `_update_view()`, which:
1. Re-creates ALL persistent editors (`_create_all_editors`)
2. Calls `expandAll()`
3. Calls `resizeColumnToContents(0)`

Every IC4 property notification triggers `dataChanged` on the proxy, which re-opens ALL persistent editors. This could cause:
- Hundreds of editor widgets destroyed and recreated per notification
- Geometry thrashing where editors are created before column widths are finalized
- Combo box popups forcibly closed and recreated during interaction

The C++ code re-creates editors in `update_view()` too, but the C++ `dataChanged` is more targeted (single-item notification, not full rebuild).

**Fix**: Only re-create editors when the model structure actually changes (e.g., filter change), not on every property value notification. Consider separating `_proxy_data_changed` from `_proxy_layout_changed` handling.

#### A5. Editor `setContentsMargins(0, 0, 2, 0)` Conflicts with C++ Pattern
**Impact: LOW** — The C++ code uses `setContentsMargins(0, 0, 8, 0)` on editors (from `createEditor`) and `setContentsMargins(8, 7, 0, 7)` in `PropControlBase`. The Python code uses `(0, 0, 2, 0)` on the editor and `(2, 4, 0, 4)` in `PropControlBase`. These differences shouldn't prevent stretching, but mismatched margins may cause visual alignment issues.

#### A6. `QTreeView::item` Stylesheet May Constrain Item Rects
**Impact: LOW-MEDIUM** — The stylesheet `PROPERTY_TREE_VIEW_STYLE` sets `background: palette(window)` on `QTreeView::item`. This doesn't directly constrain width, but complex QSS on tree items can interfere with how Qt calculates item rects that are passed to `updateEditorGeometry` via `option.rect`.

#### A7. `PropControlBase` Internal Layout Has `QHBoxLayout` with Margins
**Impact: LOW** — Each `PropControlBase` (the editor widget) creates its own `QHBoxLayout` with `setContentsMargins(2, 4, 0, 4)` and `setSpacing(2)`. The editor is sized by `updateEditorGeometry(option.rect)`, but the internal layout then positions child widgets within those margins. The child widgets should still fill the remaining space if stretch factors are correct. But if the parent QHBoxLayout has any issues with its size constraints, the children may not stretch properly.

#### A8. Delegate Not Parented to the View
**Impact: LOW** — `PropertyTreeItemDelegate.__init__` calls `super().__init__()` with no parent. The C++ pattern passes `self` (the widget) as parent. Without a parent, Qt may not properly track delegate lifetime or re-trigger geometry updates. However, `setItemDelegateForColumn` should handle the association.

---

## Problem B: Enumeration Controls Not Visible / Interactive

### ~~Possible Causes (DEPRECATED)~~

~~Note: B1-B8 below are superseded by the refined analysis in "Problem B-1" and "Problem B-2" sections above.~~
