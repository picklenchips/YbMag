# ic4-demoapp - python

Python3 camera-centered application originally from [ic4-examples/python/qt6/demoapp](https://github.com/TheImagingSource/ic4-examples/tree/master/python/qt6/demoapp) built with IC4 and PyQt6. 

1. Converted C++-native PySide6 dialogs from [ic4-examples/cpp/qt6/common/qt6-dialogs](https://github.com/TheImagingSource/ic4-examples/tree/master/cpp/qt6/common/qt6-dialogs) to PyQt6. 
2. Added dynamic theming support (light/dark) based on system palette and time of day.
3. Added multiple devices custom to the YbMag experiment, including
  - rotary motor (tuning laser polarization)
  - power supplies (for controlling static magnetic field coils)
  - 
4. Expanded on camera display functionality with custom overlays, ROI selection.

# Setup

pip install -r ./requirements.txt
python3 ./demoapp.py
