"""
Unified power-supply manager that wraps RigolManager and HP6653AManager.

Presents a single ``.supplies`` list and ``.scan()`` method so the UI layer
does not need to know which back-end managers exist.

No Qt dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

from devices.rigol_dp832a import RigolDP832A, RigolManager
from devices.hp6653a import HP6653A, HP6653AManager

# Type alias for any supply object the dialog can display
AnySupply = Union[RigolDP832A, HP6653A]

SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / "app" / "settings" / "settings.json"
)


def _load_settings() -> Dict[str, Any]:
    try:
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


class PowerSupplyManager:
    """Unified manager for all supported DC power supplies.

    Delegates to:
      - ``RigolManager``   for USB-TMC Rigol DP8xx supplies
      - ``HP6653AManager`` for GPIB HP 6653A supplies via Prologix
    """

    def __init__(self) -> None:
        settings = _load_settings()
        hp_cfg = settings.get("hp6653a", {})

        self._rigol = RigolManager()
        self._hp = HP6653AManager(
            explicit_port=hp_cfg.get("resource_name"),
            gpib_address=hp_cfg.get("gpib_address", 5),
        )

    @property
    def supplies(self) -> List[AnySupply]:
        """All known supplies (Rigol + HP) in discovery order."""
        result: List[AnySupply] = []
        result.extend(self._rigol.supplies)
        result.extend(self._hp.supplies)
        return result

    def scan(self) -> List[AnySupply]:
        """Scan for all supported supply types and return the combined list."""
        self._rigol.scan()
        self._hp.scan()
        return self.supplies

    def close_all(self) -> None:
        """Disconnect every supply from every back-end."""
        self._rigol.close_all()
        self._hp.close_all()
