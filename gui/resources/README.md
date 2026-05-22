# resources/

Theme, stylesheet, and icon-asset management. Both exported classes are singletons — obtain them via the `get_*` factory functions rather than constructing directly.

## Exports

| Symbol | Description |
|--------|-------------|
| `StyleManager` / `get_style_manager()` | Applies QSS to the `QApplication`; tracks current `ThemeMode` |
| `ThemeMode` | Enum: `LIGHT`, `DARK`, `AUTO` (follows OS setting) |
| `ResourceSelector` / `get_resource_selector()` | Resolves theme-aware asset paths (e.g. toolbar icons) |

## Assets

| Path | Description |
|------|-------------|
| `styles/base.qss` | Base stylesheet applied regardless of theme |
| `styles/theme_dark.qss` | Dark-theme overrides |
| `styles/theme_light.qss` | Light-theme overrides |
| `images/+theme_dark/` | Icon variants for dark theme |
| `images/+theme_light/` | Icon variants for light theme |

`ResourceSelector` picks the correct `+theme_*` subfolder at runtime based on the active `ThemeMode`.
