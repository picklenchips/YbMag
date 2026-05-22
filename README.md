# Yb Magnetometer Control & Simulation

> Experimental control, simulation, and digital twin of the Yb magnetometer experiment. 
> `PyQt6` GUI for central control of all modules. 
> `QuTiP` fluorescence simulation. 
> `PyTorch` ML pipeline for B-field extraction. 
> `opencv` for image processing and analysis.


Run `python app.py` to launch the GUI.

## Goal

Demonstrate measurement of dynamic B fields at fast time dynamics, automate vector imaging, and wrap it all up in an efficient GUI for central control of all modules. The excited state lifetime of Yb is 875 ns — the system should show readout of imaging at this timing speed via stroboscopic measurement.

## Modules

| Module | README | Description |
|--------|--------|-------------|
| `gui/` | [`gui/README.md`](gui/README.md) | PyQt6 GUI, camera, device dialogs |
| `devices/` | [`devices/README.md`](devices/README.md) | Qt-free hardware drivers |
| `pipeline/` | — | HDR, ROI, and DC power coordination (bridges devices ↔ GUI) |
| `simulation/` | [`simulation/README.md`](simulation/README.md) | QuTiP Lindblad physics simulation |
| `analysis/` | [`analysis/README.md`](analysis/README.md) | Qt-free data analysis scripts |
| `magtorch/` | [`magtorch/README.md`](magtorch/README.md) | PyTorch ML pipeline for fluorescence simulation |

## Action Items (Hardware / Integration)

- [ ] Integrate and test pulse generation electronics
- [ ] Figure out coil geometry susceptibility factors
- [ ] Assemble and test fast comb generation
- [ ] Build and integrate synchronized timing control for stroboscopic measurement

## Next Steps (Software)

### Image Analysis

- [ ] **Remove scattering noise:** capture reference image (laser on, no fluorescence — drive static B past resonance); apply at various exposures for HDR-style correction; assume $I \propto P \Delta t$
- [ ] Automatically identify and mask **bad pixels** (`np.nan`)
- [ ] **Alignment:** auto-align to atom $\bar{\mathbf{v}}$ using OpenCV bounding box (with blur)
- [ ] **Dark line extraction:** find local minima along center $\bar{\mathbf{v}}$ line; threshold via max of dark-line mins; connected components for dark/light blobs; fit line equations and rings
- [ ] Moving average display using `ImageBuffer`; apply arbitrary image analysis (OpenCV filters, edge detection, colormap) via Python connection
- [ ] Load saved images into a standalone display/visualizer; explore Plotly HTML viewer for interactive plots

### Automation

- [ ] Automate **B field zeroing** (subroutine: take cleaned image → null field)
- [ ] Automate and test **HDR imaging**: characterize role of exposure with 1 kHz rep rate / 10 µs laser strobing; add $N_\text{shots}$ integration parameter tied to Digilent rep rate

### GUI / Display

- [ ] Camera settings tab with: GainAuto checkbox, Gain (greyed if auto), BlackLevel, Gamma, ExposureAuto, ExposureTime, AcquisitionFrameRate
- [ ] Apply arbitrary Python script to each frame via analysis library
- [ ] Fix camera settings dialog
- [ ] Improve logging: dedicated log files + color-coded log viewer in GUI
- [ ] PyQtGraph plotting integration
- [ ] Integrate image analysis scripts into GUI
- [ ] Example notebook for `ATSolver` — fit magnetometer data to extract B field strength, relaxation times, etc.
- [ ] Re-create fluorescence simulation in PyTorch for parameter optimization (see `magtorch/`)

## Known Bugs

- [ ] **Camera exposure settings:** `PROPENUMERATIONCONTROL` not rendering correctly in camera settings dialog
- [ ] **ROI after decimation:** exiting crop after decimation broken — decimation/binning offsets not accounted for in ROI measurements
- [ ] **EllMotor disconnect status:** motor correctly completes a step but GUI reports "error: did not finish" — likely off-by-tolerance; fix: detect near-target condition and retry step in same direction instead of erroring
- [ ] **Power supplies:** no "toggle all on/off" quick control (supplies retain their internal settings when toggled)
