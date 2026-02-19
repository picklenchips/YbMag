"""
Digilent device control using the Digilent Waveforms SDK.
"""

import ctypes
import os


class DigilentController:
    """
    Digilent device control using the Digilent Waveforms SDK.
    """

    def __init__(self):
        self.connected = False
        if os.name == "nt":
            self.dwf = ctypes.cdll.LoadLibrary("dwf.dll")  # Windows
        else:
            self.dwf = ctypes.cdll.LoadLibrary("libdwf.so")  # macOS/Linux
        self.hdwf = ctypes.c_int()
        try:
            self.open()
        except RuntimeError as e:
            print(f"Error initializing Digilent device: {e}")

    def open(self) -> bool:
        self.dwf.FDwfDeviceOpen(ctypes.c_int(-1), ctypes.byref(self.hdwf))
        if self.hdwf.value == 0:
            raise RuntimeError("Digilent not found")
        self.connected = True 
        return True

    def configure(self, pulse_width, repetition_rate):
        period = 1.0 / repetition_rate
        self.dwf.FDwfDigitalOutReset(self.hdwf)

        for ch in [0, 1, 2]:
            self.dwf.FDwfDigitalOutEnableSet(self.hdwf, ch, 1)
            self.dwf.FDwfDigitalOutTypeSet(self.hdwf, ch, 1)
            self.dwf.FDwfDigitalOutPulseWidthSet(self.hdwf, ch, pulse_width)
            self.dwf.FDwfDigitalOutPeriodSet(self.hdwf, ch, period)

    def start(self):
        self.dwf.FDwfDigitalOutConfigure(self.hdwf, 1)

    def stop(self):
        self.dwf.FDwfDigitalOutConfigure(self.hdwf, 0)

    def close(self):
        self.dwf.FDwfDeviceClose(self.hdwf)
