"""
Factory for creating property controls
Translated from C++ ic4-examples/PropertyControls.cpp
"""

from PyQt6.QtWidgets import QWidget, QLabel
from typing import Optional

import imagingcontrol4 as ic4
from .props.prop_control_base import PropSelectedFunction, StreamRestartFilterFunction
from .props.prop_boolean_control import PropBooleanControl
from .props.prop_category_control import PropCategoryControl
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
    PropertyType,
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

        if prop.type == PropertyType.INTEGER:
            assert isinstance(prop, PropInteger)  # for type check
            widget = PropIntegerControl(prop, parent, grabber)
        elif prop.type == PropertyType.COMMAND:
            assert isinstance(prop, PropCommand)  # for type check
            widget = PropCommandControl(prop, parent, grabber)
        elif prop.type == PropertyType.STRING:
            assert isinstance(prop, PropString)  # for type check
            widget = PropStringControl(prop, parent, grabber)
        elif prop.type == PropertyType.ENUMERATION:
            assert isinstance(prop, PropEnumeration)  # for type check
            widget = PropEnumerationControl(prop, parent, grabber)
        elif prop.type == PropertyType.BOOLEAN:
            assert isinstance(prop, PropBoolean)  # for type check
            widget = PropBooleanControl(prop, parent, grabber)
        elif prop.type == PropertyType.FLOAT:
            assert isinstance(prop, PropFloat)  # for type check
            widget = PropFloatControl(prop, parent, grabber)
        elif prop.type == PropertyType.CATEGORY:
            assert isinstance(prop, PropCategory)  # for type check
            widget = PropCategoryControl(prop, parent)
        else:
            return None

        # Register callbacks if widget was created
        if widget and hasattr(widget, "register_stream_restart_filter"):
            if restart_func:
                widget.register_stream_restart_filter(restart_func)
            if selected_func:
                widget.register_prop_selected(selected_func)

        return widget

    except Exception:
        return None
