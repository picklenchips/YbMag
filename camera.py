"""TODO: camera SDK, and specific camera initialization/acquisition code."""

import numpy as np
import time, os
from imagingcontrol4.library import Library
from imagingcontrol4.grabber import Grabber, StreamSetupOption
from imagingcontrol4.snapsink import SnapSink
from imagingcontrol4.propconstants import PropId
from imagingcontrol4.properties import Property, PropFloat, PropInteger
from imagingcontrol4.ic4exception import IC4Exception
from imagingcontrol4.devenum import DeviceEnum

"""TODO: camera SDK, and specific camera initialization/acquisition code."""
if os.name != "nt":
    raise NotImplementedError("Camera control only implemented for Windows (IC4 SDK)")


class Camera:
    """
    Driving the DMK 33UX174 camera using the IC4 Python SDK. Only works with Windows.

    only works with windows... need to download driver... IC4 SDK
    https://www.theimagingsource.com/en-us/support/download/icimagingcontrol4win-1.0.0.2416/
    Documentation found at https://www.theimagingsource.com/en-us/documentation/ic4python/
    Plenty of examples on the github
    """

    def __init__(self):
        Library.init()
        self.grabber = Grabber()
        self.sink = SnapSink()
        self.connected = False
        self.MIN_EXPOSURE_US = 1000

    def connect(self):
        # Open the first available video capture device
        device_list = DeviceEnum.devices()
        print(f"Found {len(device_list)} devices")
        for d in device_list:
            # DeviceInfo objects
            # https://www.theimagingsource.com/en-us/documentation/ic4python/api-reference.html#imagingcontrol4.devenum.DeviceInfo
            print(
                f"Model: {d.model_name}, Serial: {d.serial}, Interface: {d.interface.display_name}"
            )
        first_device_info = device_list[0]
        self.grabber.device_open(first_device_info)
        self.connected = True

    def configure(self, resolution=(640, 480), exposure_us=1000):
        """
        FUTURE: want to change this so that we can pass in a region of interest (ROI)
        that will set width, hieght, and offset_x, offset_y.

        also want
        - horizontal and vertical binning (combining adjacent pixels to increase sensitivity at the cost of resolution)
            - between 1 and 4
        - horizontal and vertical decimation (skipping pixels to increase frame rate at the cost of resolution)

        also want to look into trigger control. relevant params:
        - trigger_mode: "Off", "On"
        - trigger source: Any, Line 1, Software
        - trigger delay
        - trigger debounce time
        - trigger mask time
        - trigger activation: Rising/Falling Edge
        - trigger selector: Frame Start, Exposure Start
        - exposure time: between 1000µs and 100000µs (1ms to 100ms) for our camera. want to set this as low as possible while still getting good images, to minimize motion blur.
        - acquisition frame rate: between 1Hz and variable (max frame rate is dependent on resolution)
        """
        # Set the resolution
        self.grabber.device_property_map.set_value(PropId.WIDTH, resolution[0])
        self.grabber.device_property_map.set_value(PropId.HEIGHT, resolution[1])
        # set origin of ROI to top-left corner
        # actually we would want to change this to region of interest...
        self.grabber.device_property_map.set_value(PropId.OFFSET_AUTO_CENTER, "Off")
        self.grabber.device_property_map.set_value(PropId.OFFSET_X, 0)
        self.grabber.device_property_map.set_value(PropId.OFFSET_Y, 0)
        # framerate max/min
        fps = self.grabber.device_property_map[PropId.ACQUISITION_FRAME_RATE]
        assert isinstance(
            fps, PropFloat
        ), f"Expected PropFloat for fps {fps}, got {type(fps)}"
        max_fps = fps.maximum
        min_fps = fps.minimum
        print(f"Camera supports frame rates between {min_fps} and {max_fps} fps")
        # Configure the exposure time to 5ms (5000µs)
        self.grabber.device_property_map.set_value(PropId.EXPOSURE_AUTO, "Off")
        self.grabber.device_property_map.set_value(PropId.EXPOSURE_TIME, exposure_us)
        # Enable GainAuto
        self.grabber.device_property_map.set_value(PropId.GAIN_AUTO, "Continuous")

    def grab_image(self):
        # Create a SnapSink. A SnapSink allows grabbing single images (or image sequences) out of a data stream.
        # Setup data stream from the video capture device to the sink and start image acquisition.
        self.grabber.stream_setup(
            self.sink, setup_option=StreamSetupOption.ACQUISITION_START
        )
        try:
            # Grab a single image out of the data stream.
            image = self.sink.snap_single(1000)

            # Print image information.
            print(f"Received an image. ImageType: {image.image_type}")

            # Save the image.
            image.save_as_bmp("test.bmp")

        except IC4Exception as ex:
            print(ex.message)

        # Stop the data stream.
        self.grabber.stream_stop()

        if self.connected:
            return self.grabber.grab_image()
        return None
