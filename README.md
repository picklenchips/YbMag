# Yb Magnetometer Control & Simulation

### Current Organization
```
ExperimentGUI
ExperimentController
  ├── AcquisitionWorker (QThread)
  ├── Digilent (C)
  ├── Camera (IC4)
  └── EllMotor (.NET)
```

Experimental GUI built with PyQt6 for controlling and monitoring the Yt magnetometer experiment. Run `python ./app/demoapp.py` to launch the GUI.

### Next Steps 
- [ ] Integrate experimental control into GUI
- [ ] Integrate Digilent trigger control into AcquisitionWorker for camera acquisition instead of Python (see example file)
- [ ] Add logging to AcquisitionWorker
- [ ] Integrate programmable DC power supply control for static B fields
- [ ] Integrate image analysis and processing scripts into GUI
- [ ] Add real-time plotting of magnetometer data
- [ ] Integrate simulation with GUI for real-time comparison of experimental and simulated data
- [ ] ipynb for example of ATSolver usage for fitting magnetometer data to extract parameters like B field strength, relaxation times, etc.
- [ ] Re-create fluorescence simulation in PyTorch for parameter optimization and fitting to experimental data