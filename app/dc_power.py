"""
I have connected to a Rigol DP832A, with programming guide found at https://www.batronix.com/pdf/Rigol/ProgrammingGuide/DP800_ProgrammingGuide_EN.pdf.

Use pyvisa to interface with all instances of the power supply (I will be connected to at least two). Create a class with methods for connecting, setting voltage and current, and querying status of each power supply. Implement auto-detection of all connected DP832A power supplies via USB-micro-B.
- Each power supply has three channels, so the class should allow control of each channel independently.
- Upon connection, query max voltage and current for each channel and store these as properties of the class.
- Implement error handling for communication issues, and ensure that the class can be used in a real-time control loop without blocking the main thread.
- Integrate this functionality into a new Qt6 widget that allows the user to control the the voltage and current settings of each channel (using BasicSlider as base), and displays the current voltage and current settings in real-time.
- Add space in the mainwindow for this new widget as a button named "Power Supplies". When clicked, it should open a new dialog with a header interface for each connected power supply, where clicking on the header shows information of connection of each power suppl as well as connected status. Each header should be expandable to show the controls for each channel of the power supply.
"""
