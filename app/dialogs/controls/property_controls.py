"""
Factory for creating property controls
Translated from C++ ic4-examples/PropertyControls.cpp
"""

from PyQt6.QtWidgets import QWidget, QLabel
from typing import Optional

import imagingcontrol4 as ic4
from .props.prop_control_base import PropSelectedFunction, StreamRestartFilterFunction
from .props.prop_boolean_control import PropBooleanControl
from .props.prop_command_control import PropCommandControl
from .props.prop_enumeration_control import PropEnumerationControl
from .props.prop_float_control import PropFloatControl
from .props.prop_integer_control import PropIntegerControl
from .props.prop_string_control import PropStringControl
from imagingcontrol4.properties import (
    Property,
    PropInteger,
    PropCommand,
    PropString,
    PropEnumeration,
    PropBoolean,
    PropFloat,
    PropCategory,
)
from imagingcontrol4.grabber import Grabber


def create_prop_control(
    prop: Property,
    parent: Optional[QWidget],
    grabber: Optional[Grabber],
    restart_func: Optional[StreamRestartFilterFunction] = None,
    selected_func: Optional[PropSelectedFunction] = None,
) -> Optional[QWidget]:
    """Create appropriate control widget for a property"""

    try:
        widget = None

        if isinstance(prop, PropInteger):
            widget = PropIntegerControl(prop, parent, grabber)
        elif isinstance(prop, PropCommand):
            widget = PropCommandControl(prop, parent, grabber)
        elif isinstance(prop, PropString):
            widget = PropStringControl(prop, parent, grabber)
        elif isinstance(prop, PropEnumeration):
            widget = PropEnumerationControl(prop, parent, grabber)
        elif isinstance(prop, PropBoolean):
            widget = PropBooleanControl(prop, parent, grabber)
        elif isinstance(prop, PropFloat):
            widget = PropFloatControl(prop, parent, grabber)
        elif isinstance(prop, PropCategory):
            # Categories are handled differently in the tree
            return None
        else:
            return None

        # Register callbacks if widget was created
        if widget and hasattr(widget, "register_stream_restart_filter"):
            if restart_func:
                widget.register_stream_restart_filter(restart_func)
            if selected_func:
                widget.register_prop_selected(selected_func)

        return widget

    except Exception as e:
        print(f"Error creating property control: {e}")
        return None
