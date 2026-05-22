# settings/

Runtime configuration files for the app and IC4 SDK.

| File | Edit? | Description |
|------|-------|-------------|
| `settings.json` | Yes | Hand-editable app config: device serial numbers, display names, poll intervals. Read fresh on every poll cycle — never cached. |
| `device.json` | No | IC4 auto-generated device state. Overwritten by IC4 on every session. |
| `codecconfig.json` | No | IC4 auto-generated codec configuration. Overwritten by IC4 on every session. |

Access `settings.json` via `_load_settings()` in `mainwindow.py` or any dialog:

```python
settings = _load_settings()
val = settings.get("power_supply_poll_interval_ms", 500)
```
