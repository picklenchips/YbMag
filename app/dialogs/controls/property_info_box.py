"""
Property info box widget for displaying detailed property information
Translated from C++ PropertyInfoBox.h
"""

from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextBlockFormat, QTextCursor
from typing import Optional
import math

from imagingcontrol4.properties import (
    Property,
    PropInteger,
    PropFloat,
    PropString,
    PropEnumeration,
    PropBoolean,
    PropCategory,
)


def _int_value_to_string(val: int, rep) -> str:
    """Format integer value based on representation (matches C++ PropIntControl::value_to_string)"""
    try:
        rep_name = str(rep).upper()
        if "BOOLEAN" in rep_name:
            return "True" if val else "False"
        elif "HEX" in rep_name:
            return f"0x{val:x}"
        elif "MAC" in rep_name:
            return ":".join([f"{(val >> (40 - i*8)) & 0xFF:02x}" for i in range(6)])
        elif "IPV4" in rep_name:
            return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"
    except Exception:
        pass
    return str(val)


def _float_text_from_value(val: float, notation=None, precision: int = 6) -> str:
    """Format float value based on display notation (matches C++ PropFloatControl::textFromValue)"""
    try:
        notation_name = str(notation).upper() if notation else ""
        if "SCIENTIFIC" in notation_name:
            return f"{val:.{precision}E}"
        if val >= math.pow(10, precision):
            return f"{val:.0f}"
        else:
            # G format for general precision
            return f"{val:.{precision}g}"
    except Exception:
        return str(val)


class PropertyInfoBox(QTextEdit):
    """Text box for displaying detailed property information"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)

    def clear(self):
        """Clear the info box"""
        self.setHtml("")

    def update(self, prop: Optional[Property]):
        """Update with property information"""
        if not prop:
            self.clear()
            return

        try:
            name = prop.name
            desc = prop.description

            text = ""
            text += f"<p style='margin-bottom:0px'><b>{name}</b></p>"
            if desc:
                text += f"<p style='margin-top:0px;margin-bottom:5px'>{desc}</p>"

            text += "<p style='margin-top:0px'>"

            is_locked = prop.is_locked
            is_readonly = prop.is_readonly

            if is_readonly:
                text += "Access: Read-Only<br/>"
            elif is_locked:
                text += "Access: Readable, Locked<br/>"
            else:
                text += "Access: Readable, Writable<br/>"

            # Type-specific information (matches C++ switch on prop.type())
            if isinstance(prop, PropCategory):
                text += "Type: Category<br/>"
            elif isinstance(prop, PropInteger):
                text += self._show_integer_info(prop)
            elif isinstance(prop, PropFloat):
                text += self._show_float_info(prop)
            elif isinstance(prop, PropString):
                text += self._show_string_info(prop)
            elif isinstance(prop, PropEnumeration):
                text += self._show_enumeration_info(prop)
            elif isinstance(prop, PropBoolean):
                text += self._show_boolean_info(prop)

            text += "</p>"
            self.setHtml(text)
        except Exception as ex:
            self.setText(str(ex))

        # Disable selection
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setReadOnly(True)
        self.setContentsMargins(8, 8, 8, 8)
        self.setStyleSheet("QTextEdit { font-size: 13px; }")

        # Line spacing
        doc = self.document()
        if doc:
            current_block = doc.firstBlock()
            if current_block.isValid():
                cursor = QTextCursor(current_block)
                block_format = current_block.blockFormat()
                block_format.setLineHeight(160, 0)  # ProportionalHeight
                cursor.setBlockFormat(block_format)
                current_block = current_block.next()

                while current_block.isValid():
                    text_cursor = QTextCursor(current_block)
                    block_format = current_block.blockFormat()
                    block_format.setLineHeight(120, 0)  # ProportionalHeight
                    text_cursor.setBlockFormat(block_format)
                    current_block = current_block.next()

    def _show_string_info(self, prop: PropString) -> str:
        """Show string property info (matches C++ showStringInfo)"""
        text = "Type: String<br/>"

        try:
            val = prop.value
            val = val.replace("@", "<span>@</span>")
            text += f"Value: {val}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        if not prop.is_readonly:
            try:
                text += f"Maximum Length: {prop.max_length}<br/>"
            except Exception:
                pass

        return text

    def _show_integer_info(self, prop: PropInteger) -> str:
        """Show integer property info (matches C++ showIntegerInfo)"""
        text = "Type: Integer<br/>"

        try:
            rep = prop.representation
        except Exception:
            rep = None

        try:
            unit = prop.unit
            if unit:
                text += f"Unit: {unit}<br/>"
        except Exception:
            pass

        try:
            val = prop.value
            text += f"Value: {_int_value_to_string(val, rep)}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        if not prop.is_readonly:
            try:
                text += f"Minimum: {prop.minimum}<br/>"
            except Exception:
                pass

            try:
                text += f"Maximum: {prop.maximum}<br/>"
            except Exception:
                pass

            # Increment mode handling (matches C++ switch on incrementMode)
            try:
                inc_mode = prop.increment_mode
                inc_mode_name = str(inc_mode).upper()

                if "INCREMENT" in inc_mode_name and "NONE" not in inc_mode_name:
                    try:
                        text += f"Increment: {prop.increment}<br/>"
                    except Exception as ex:
                        text += (
                            f"Increment: <span style='color:red'>{str(ex)}</span><br/>"
                        )
                elif "VALUESET" in inc_mode_name or "VALUE_SET" in inc_mode_name:
                    try:
                        value_set = prop.valid_value_set
                        vals = ", ".join(str(v) for v in value_set)
                        text += f"Valid Value Set: {vals}<br/>"
                    except Exception as ex:
                        text += f"Valid Value Set: <span style='color:red'>{str(ex)}</span><br/>"
            except Exception:
                # Fallback: try simple increment
                try:
                    inc = prop.increment
                    if inc:
                        text += f"Increment: {inc}<br/>"
                except Exception:
                    pass

        return text

    def _show_float_info(self, prop: PropFloat) -> str:
        """Show float property info (matches C++ showFloatInfo)"""
        text = "Type: Float<br/>"

        try:
            notation = prop.display_notation
        except Exception:
            notation = None

        try:
            precision = prop.display_precision
        except Exception:
            precision = 6

        try:
            unit = prop.unit
            if unit:
                text += f"Unit: {unit}<br/>"
        except Exception:
            pass

        try:
            val = prop.value
            text += f"Value: {_float_text_from_value(val, notation, precision)}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        if not prop.is_readonly:
            try:
                minimum = prop.minimum
                text += f"Minimum: {_float_text_from_value(minimum, notation, precision)}<br/>"
            except Exception:
                pass

            try:
                maximum = prop.maximum
                text += f"Maximum: {_float_text_from_value(maximum, notation, precision)}<br/>"
            except Exception:
                pass

            # Increment mode handling
            try:
                inc_mode = prop.increment_mode
                inc_mode_name = str(inc_mode).upper()

                if "INCREMENT" in inc_mode_name and "NONE" not in inc_mode_name:
                    try:
                        inc = prop.increment
                        text += f"Increment: {_float_text_from_value(inc, notation, precision)}<br/>"
                    except Exception as ex:
                        text += (
                            f"Increment: <span style='color:red'>{str(ex)}</span><br/>"
                        )
                elif "VALUESET" in inc_mode_name or "VALUE_SET" in inc_mode_name:
                    try:
                        value_set = prop.valid_value_set
                        vals = ", ".join(
                            _float_text_from_value(v, notation, precision)
                            for v in value_set
                        )
                        text += f"Valid Value Set: {vals}<br/>"
                    except Exception as ex:
                        text += f"Valid Value Set: <span style='color:red'>{str(ex)}</span><br/>"
            except Exception:
                try:
                    inc = prop.increment
                    if inc:
                        text += f"Increment: {_float_text_from_value(inc, notation, precision)}<br/>"
                except Exception:
                    pass

        return text

    def _show_enumeration_info(self, prop: PropEnumeration) -> str:
        """Show enumeration property info (matches C++ showEnumerationInfo)"""
        text = "Type: Enumeration<br/>"

        try:
            val = prop.value
            text += f"Value: {val}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        text += "Possible Values: "
        try:
            entries = list(prop.entries)
            first = True
            any_unavailable = False

            for entry in entries:
                try:
                    if not entry.is_available:
                        any_unavailable = True
                        continue

                    if not first:
                        text += ", "
                    else:
                        first = False
                    # C++ uses entry.name(), not displayName()
                    text += entry.name
                except Exception:
                    pass

            text += "<br/>"

            if any_unavailable:
                text += "Unavailable Values: "
                first = True
                for entry in entries:
                    try:
                        if entry.is_available:
                            continue

                        if not first:
                            text += ", "
                        else:
                            first = False
                        text += entry.name
                    except Exception:
                        pass
                text += "<br/>"

        except Exception as ex:
            text += f"<span style='color:red'>{str(ex)}</span><br/>"

        return text

    def _show_boolean_info(self, prop: PropBoolean) -> str:
        """Show boolean property info (matches C++ showBooleanInfo)"""
        text = "Type: Boolean<br/>"

        try:
            val = prop.value
            text += f"Value: {'True' if val else 'False'}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        return text
