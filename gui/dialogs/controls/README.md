# dialogs/controls/

Reusable device-agnostic composite widgets used by dialogs. 

## Exports

| Class | File | Description |
|-------|------|-------------|
| `PropertyTreeWidget` | `property_tree_widget.py` | Model-view tree for an IC4 `PropertyMap` |
| `PropertyTreeWidgetSettings` | `property_tree_widget.py` | Config dataclass for `PropertyTreeWidget` |
| `TabbedPropertyWidget` | `tabbed_property_widget.py` | `QTabWidget` wrapping multiple `PropertyTreeWidget`s |
| `PropertyInfoBox` | `property_info_box.py` | Read-only details panel for a selected IC4 property |
| `BasicSlider` | `basic_slider.py` | Integer/float slider with synchronized text input |

## Other modules (not re-exported)

| File | Description |
|------|-------------|
| `engineering_slider.py` | `BasicSlider` variant with engineering-notation (µ, m, k) formatting |
| `binningdecimation.py` | Combined binning + decimation combo-box control |
| `property_controls.py` | Dispatches IC4 property type → correct `props/` leaf widget |
| `property_tree_model.py` | `QAbstractItemModel` backing `PropertyTreeWidget` |

Per-type leaf widgets are in [`props/`](props/).
