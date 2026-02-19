"""
Property info box widget for displaying detailed property information
Translated from C++ PropertyInfoBox.h
"""

from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextBlockFormat, QTextCursor
from typing import Optional

from imagingcontrol4.properties import (
    Property,
    PropInteger,
    PropFloat,
    PropString,
    PropEnumeration,
    PropBoolean,
    PropCategory,
)


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

            # Add type-specific information
            if isinstance(prop, PropInteger):
                text += self._show_integer_info(prop)
            elif isinstance(prop, PropFloat):
                text += self._show_float_info(prop)
            elif isinstance(prop, PropString):
                text += self._show_string_info(prop)
            elif isinstance(prop, PropEnumeration):
                text += self._show_enumeration_info(prop)
            elif isinstance(prop, PropBoolean):
                text += self._show_boolean_info(prop)
            elif isinstance(prop, PropCategory):
                text += "Type: Category<br/>"

            text += "</p>"
            self.setHtml(text)
        except Exception as ex:
            self.setText(str(ex))

        # Disable selection and editing
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setReadOnly(True)
        self.setContentsMargins(8, 8, 8, 8)
        self.setStyleSheet("QTextEdit { font-size: 13px; }")

        # Set line spacing
        doc = self.document()
        if doc:
            current_block = doc.firstBlock()
            if current_block.isValid():
                cursor = QTextCursor(current_block)
                block_format = current_block.blockFormat()
                # Use integer value 0 for ProportionalHeight
                block_format.setLineHeight(160, 0)
                cursor.setBlockFormat(block_format)
                current_block = current_block.next()

                while current_block.isValid():
                    text_cursor = QTextCursor(current_block)
                    block_format = current_block.blockFormat()
                    block_format.setLineHeight(120, 0)
                    text_cursor.setBlockFormat(block_format)
                    current_block = current_block.next()

    def _show_string_info(self, prop: PropString) -> str:
        """Show information about a string property"""
        text = "Type: String<br/>"

        try:
            val = prop.value
            # Escape @ symbols
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
        """Show information about an integer property"""
        text = "Type: Integer<br/>"

        try:
            unit = prop.unit
            if unit:
                text += f"Unit: {unit}<br/>"
        except Exception:
            pass

        try:
            val = prop.value
            text += f"Value: {val}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        if not prop.is_readonly:
            try:
                minimum = prop.minimum
                text += f"Minimum: {minimum}<br/>"
            except Exception:
                pass

            try:
                maximum = prop.maximum
                text += f"Maximum: {maximum}<br/>"
            except Exception:
                pass

            try:
                increment = prop.increment
                if increment:
                    text += f"Increment: {increment}<br/>"
            except Exception:
                pass

        return text

    def _show_float_info(self, prop: PropFloat) -> str:
        """Show information about a float property"""
        text = "Type: Float<br/>"

        try:
            unit = prop.unit
            if unit:
                text += f"Unit: {unit}<br/>"
        except Exception:
            pass

        try:
            val = prop.value
            text += f"Value: {val}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        if not prop.is_readonly:
            try:
                minimum = prop.minimum
                text += f"Minimum: {minimum}<br/>"
            except Exception:
                pass

            try:
                maximum = prop.maximum
                text += f"Maximum: {maximum}<br/>"
            except Exception:
                pass

            try:
                increment = prop.increment
                if increment:
                    text += f"Increment: {increment}<br/>"
            except Exception:
                pass

        return text

    def _show_enumeration_info(self, prop: PropEnumeration) -> str:
        """Show information about an enumeration property"""
        text = "Type: Enumeration<br/>"

        try:
            val = prop.value
            text += f"Value: {val}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        text += "Possible Values: "
        try:
            entries = prop.entries
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
                    text += entry.display_name
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
                        text += entry.display_name
                    except Exception:
                        pass
                text += "<br/>"

        except Exception as ex:
            text += f"<span style='color:red'>{str(ex)}</span><br/>"

        return text

    def _show_boolean_info(self, prop: PropBoolean) -> str:
        """Show information about a boolean property"""
        text = "Type: Boolean<br/>"

        try:
            val = prop.value
            text += f"Value: {'True' if val else 'False'}<br/>"
        except Exception as ex:
            text += f"Value: <span style='color:red'>{str(ex)}</span><br/>"

        return text
