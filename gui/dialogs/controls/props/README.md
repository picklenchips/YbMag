# dialogs/controls/props/

Per-type leaf widgets for IC4 `PropertyMap` nodes. Each class renders and edits one IC4 property type. Instantiated by `property_controls.py` based on the node type returned by IC4.

All classes inherit `PropControlBase` (`prop_control_base.py`), which handles the `_programmatic` guard that suppresses `valueChanged` signals during poll-driven updates.

## Exports

| Class | IC4 property type | Widget |
|-------|------------------|--------|
| `PropBooleanControl` | Boolean | `QCheckBox` |
| `PropCategoryControl` | Category | Read-only label (non-interactive grouping node) |
| `PropCommandControl` | Command | `QPushButton` |
| `PropEnumerationControl` | Enumeration | `QComboBox` |
| `PropFloatControl` | Float | `QDoubleSpinBox` |
| `PropIntegerControl` | Integer | `QSpinBox` |
| `PropStringControl` | String | `QLineEdit` |
