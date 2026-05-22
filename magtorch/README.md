# End-To-End ML Pipeline for YbMag Simulation

## I. Goals

### 1. Data Generation
- Accept real camera data or generate synthetic data via internal forward propagation
- **Measurement target**: the 7D field $\vec{B}(\vec{x})$ where $\vec{x} = [t, x, y, z]^\top$, discretized as a PyTorch tensor over the imaging volume and time
    - Sweep AM square-wave modulation frequency → recover $|\vec{B}|$ at each spatial position
    - Sweep laser polarization angle $\chi$ (Elliptec rotary motor) → recover full vector direction $\hat{B}$
    - Together reconstruct all three components $(B_x, B_y, B_z)$ over $(x, y, z)$
- **Input data**: intensity $I(\vec{x})$ sampled on a 4D lattice,
$$I = \sum_{n,i,j,k} I(t_n, x_i, y_j, z_k)\,\Delta t\,\Delta X\,\Delta Y\,\Delta Z$$
where camera pixels tile the 2D imaging area $(\Delta X_i, \Delta Y_j)$, depth $\Delta Z_k$ is resolved by translating optics, and $N$ frames are sampled at interval $\Delta t = \Delta T/(N-1)$
- Create pure QuTiP simulation for independent accuracy benchmarking
- Integrate with device control code so model can tune experimental parameters in real time! (ensure clipping) (RL-based optimization)
- Eventually extend to HDR multi-exposure fusion for increased dynamic range
- Integrate with GUI for real-time visualization of predictions and control
- Consider compression techniques here for efficient storage and training on large datasets (e.g. autoencoder-based latent space)... how do constraints like Maxwell's equations affect the optimal latent space representation?

### 2. Data Preprocessing
- Normalize data
- Handle missing values
- Split into training, validation, and test sets

### 3. Model Selection
- **Physics-informed neural operator**: encode Maxwell's equations
$$\vec{\nabla}\cdot\vec{B} = 0,\qquad \vec{\nabla}\times\vec{E} = -\partial_t\vec{B},\qquad \vec{\nabla}\times\vec{B} = \mu_0\vec{J}+\mu_0\epsilon_0\,\partial_t\vec{E}$$
directly in the architecture, yielding a continuous differentiable field $\vec{B}(\vec{x})$ that interpolates between sparse measurements
    - Maxwell constraints reduce the number of measurement hyperplanes required to fully reconstruct $\vec{B}$; the model performs physics-constrained interpolation rather than brute-force dense sampling
    - Note: $\partial_t\vec{B}\neq 0$ induces $\vec{\nabla}\times\vec{E}\neq 0$ (Faraday) — a time-varying applied field generates an $\vec{E}$-curl that back-reacts on atom dynamics via the AC Stark (Autler-Townes) shift
- Probabilistic model capturing correlated and uncorrelated noise with learnable inter-source coupling
- Ensemble methods for improved robustness
- See model architecture / pipeline below

### 4. Model Training
- Train on training dataset with appropriate loss functions and optimizers
- Early stopping on validation loss
- Hyperparameter tuning via Bayesian optimization or grid/random search
- RL algorithms (PPO, DDPG, SAC, TD3) to optimize control parameters

### 5. Model Evaluation
- Evaluate on validation and test sets
- Metrics: MSE, precision, recall, F1
- Visualizations: confusion matrix, ROC, precision-recall curves

---

## II. Model Architecture
Everything should be differentiable, PyTorch-based, and GPU-accelerated wherever possible. Minimize CPU/GPU handoffs. Modular design with clear separation between components (input, noise models, physics forward propagation, output, loss).

### 1. Input Layer
- Accepts raw camera data or synthetic simulation data
    - Camera parameters: exposure time $\tau$, gain $g$, pixel size $\delta$, quantum efficiency $\eta$ ($\gamma \to \sigma^2$)
    - **FUTURE**: Multi-camera / sensor fusion for smart sparse data combination
- **Input tensor shape**: $(N_\text{batch}, N_t, H, W)$ — batched over time steps, variable sequence length support
    - Time-correlated noise structure depends on sample rate $1/\Delta t$
- Laser parameters:
    - Polarization angle $\chi$; choice of working basis (circular $\sigma^\pm$ vs. linear $\pi$) affects atom-photon coupling matrix elements and should be matched to the quantization axis set by $\vec{B}$
    - Power $P$, linewidth $\delta\nu$, broadening $\Delta\nu$
    - AOM-controlled spectrum — retain only frequency components within camera exposure $\tau$ and atomic memory $\sim 1/\Gamma$
- Known experimental controls: $\chi$, oven temperature $T_\text{oven}$, $P$, $\lambda$
- Applied field: static coil contribution $\vec{B}_\text{static}$ and dynamic pulser $\vec{B}_\text{dyn}(t)$

### 2. Input Noise Models

**Laser noise:**
- Transmission lineshape is a **Voigt profile** — convolution of:
    - Gaussian Doppler broadening: $\Delta\nu_D = (\nu_0/c)\sqrt{8\ln 2\, k_BT/m}$
    - Lorentzian natural linewidth $\Gamma$ (spontaneous decay) power-broadened to $\Gamma\sqrt{1+I/I_\text{sat}}$
- Multi-mode lasing: longitudinal cavity modes spaced by $c/2L$ contribute spurious frequency components
- Cavity locking jitter: residual frequency uncertainty within locking bandwidth

**Atom noise:**
- Atoms have a Maxwell-Boltzmann speed distribution; the longitudinal component $v_z$ Doppler-shifts the resonance by $\Delta\nu = \nu_0 v_z/c$
- Atomic polarizability: electric dipole $\vec{d} = -e\vec{r}$ couples to $\vec{E}$ (AC Stark / Autler-Townes shift $\propto |\Omega|^2/\Delta$); magnetic dipole $\vec{\mu} = -g_J\mu_B\vec{J}$ couples to $\vec{B}$ (Zeeman shift)
- Zeeman sublevel energies: $\Delta E_{m_J} = m_J g_J \mu_B B$ — three distinct $\Delta m_J = 0,\pm 1$ resonances (electric dipole selection rules)
- Spontaneous decay at rate $\Gamma$; laser-driven stimulated emission between levels $i\!\to\!j$ at rate $W_{ij} \propto I/I_\text{sat}$
- Harmonic sideband approach excites 2-photon dark-state transitions ($\Delta m_J = \pm 2$ coherences) — observe dark bands rather than bright resonances

**Camera noise:**
- Shot noise: Poisson statistics $\sigma_\text{shot}^2 = \langle N_\gamma \rangle$ — dominant at low photon flux (image edges, low atom density)
- Readout noise $\sigma_\text{ro}^2$, dark current $\sigma_\text{dc}^2$, background $\sigma_\text{bg}^2$
- Intensity averaging over exposure: $\langle I\rangle_\tau = \tau^{-1}\!\int_0^\tau I(t)\,dt$; no phase information (fluorescence is incoherent)
- **Hanle effect**: when the polarization geometry $\hat{\chi}_k\times\hat{\chi}_E$ aligns with $\vec{B}$, ground-state Zeeman coherences reduce fluorescence — angle-dependent systematic requiring explicit modeling

**Mechanical / magnetic field noise:**
- Vibrations at mechanically relevant frequencies shift beam pointing and camera alignment
- Thermal expansion of optical mounts
- Power supply ripple and low-frequency environmental $\vec{B}$ drifts
- Dynamic pulser: timing jitter, amplitude noise — characterize noise spectrum (white vs. colored? Gaussian vs. non-Gaussian? stationary? correlated with other sources?)

**Atom beam noise:**
- Maxwell-Boltzmann distribution $f(v)\propto v^2 e^{-mv^2/2k_BT}$ sets transverse and longitudinal velocity spread at oven temperature $T$
- Ballistic diffraction spreads the beam; spatial atom density in the imaging region depends on $T$, aperture geometry, and collimation

### 3. Physics-Based Forward Propagation
Predict fluorescence signal by composing field model → laser model → Lindblad solver → camera model.

- **Field model**: parameterize via vector and scalar potentials in Lorenz gauge ($\vec{\nabla}\cdot\vec{A} + c^{-2}\partial_t\phi = 0$); reconstruct $\vec{B} = \vec{\nabla}\times\vec{A}$ and $\vec{E} = -\vec{\nabla}\phi - \partial_t\vec{A}$
- **Laser model**: quasi-monochromatic beam with spatial profile from optical system; include multi-mode corrections if $\delta\nu \gtrsim \Gamma$
- **Lindblad (GKSL) master equation**:
$$\dot{\rho} = -\frac{i}{\hbar}[H,\rho] + \sum_k \Gamma_k\!\left(L_k\rho L_k^\dagger - \tfrac{1}{2}\{L_k^\dagger L_k,\rho\}\right)$$
with $H = H_\text{atom} + H_\text{Zeeman} + H_\text{AL}$ where:
    - $H_\text{Zeeman} = g_J\mu_B\vec{J}\cdot\vec{B}$ (Zeeman splitting)
    - $H_\text{AL} = -\vec{d}\cdot\vec{E}_\text{laser}$ (atom-laser coupling, Rabi drive)
    - Jump operators $L_k$ encode spontaneous decay channels at rates $\Gamma_k$
    - Include Hanle coherences, Doppler-shifted detunings, full multi-level structure (determine minimum level count for target accuracy)
    - Target GPU-parallelized density matrix propagation
- **Fluorescence integration**: integrate emitted photon rate $\Gamma\rho_{ee}$ over atom trajectories across the beam spatial distribution; propagate to camera plane via ray optics (or wave optics if diffraction is relevant)
- **Camera model**: apply exposure averaging, PSF convolution, gain $g$, quantization, and all noise contributions ($\sigma_\text{shot}$, $\sigma_\text{ro}$, $\sigma_\text{dc}$)

### 4. Output Layer
- Output: predicted fluorescence tensor of shape $(N_\text{batch}, N_t, H, W)$, directly comparable to camera data
- Intermediate outputs for interpretability: per-level populations $\rho_{ii}(t)$, per-step fluorescence, intermediate field estimates
- Output basis choice:
    - Pixel space (direct camera comparison)
    - Atomic state space (full density matrix $\rho$)
    - Natural fluorescence modes → pixel space via differentiable camera model
- Dimensionality reduction (PCA, autoencoder) — determine optimal placement in the pipeline

### 5. Loss Function
- Base: MSE between predicted and measured fluorescence $\mathcal{L}_\text{MSE} = \|I_\text{pred} - I_\text{meas}\|^2$
- Physics constraints:
    - $\vec{\nabla}\cdot\vec{B} = 0$ (no magnetic monopoles)
    - Conservation of probability: $\text{Tr}[\rho] = 1$, positivity $\rho \geq 0$
- Temporal autocorrelation loss: captures time-correlated noise beyond pointwise MSE
- Regularization (L1/L2) on model parameters
- Entropy-based uncertainty penalties
- Adversarial / CNN-based spatial correlation loss
- RL-based control optimization (PPO, DDPG, SAC, TD3) over:
    - Laser: $P$, $\chi$, $\lambda$
    - Field: static $\vec{B}$, pulser timing/amplitude
    - Camera: $\tau$, $g$
- HDR extension: differentiable multi-exposure fusion to increase effective dynamic range
- Compressed sensing: sparse basis representations with continuous interpolation between discretizations

### 6. Training Loop
- Iterative train/validate with backpropagation and gradient-based optimization
- Early stopping on validation loss
- Bayesian hyperparameter optimization (or RL-based)
- Monte Carlo trajectory sampling for Lindblad solver
- Train individual components on minimal datasets first; increase dimensionality progressively
- End-to-end fine-tuning after component-wise pretraining

---

## III. Benchmarking

### Approach
- Benchmark each component separately with appropriate datasets and metrics
- Progress from simple to complex; measure each component's contribution to end-to-end performance
- Noise/bias analysis: $\vec B$-forward (bottom-up) and $I$-backward (top-down)

### Questions
- How does noise in each parameter propagate through the model — what is the SNR evolution per layer?
- What is the bias-variance tradeoff as the estimation network grows?
- How does performance scale with training data vs. theoretical noise-limited bounds?
- CPU/GPU division of labor; runtime per layer, especially the GKSL (Lindblad) solver vs. QuTiP
- What cost function best avoids local minima under correlated, non-Gaussian noise?
- Which approximations are most load-bearing — what degrades first when each is removed?
- Can sparse Maxwell-constrained sweeps fully recover $\vec{B}(\vec{x},t)$, and what is the minimum number of required measurement hyperplanes?
- **Can we achieve QuTiP-comparable accuracy at significantly reduced runtime via a learned Lindblad propagator?**
    - Reuse any existing work on GKSL solvers using neural networks
    - Conduct ablation studies on the physics-informed architecture to determine which constraints are most critical for accurate interpolation

---

## V. Syntax
- PyTorch throughout for differentiability and GPU acceleration
- Modular code: clear separation between input, noise models, physics propagation, output, loss
- Consistent naming conventions
- reStructuredText docstrings; **ONGOING**: Sphinx documentation with API references, linked examples
- Git version control
- Unit tests per component
- Jupyter notebooks as standalone tutorials per component; benchmarking cell at end of each

---

## VI. Filestructure

```
magtorch/
├── data/                          # Raw and processed data (camera and synthetic)
│   ├── camera/
│   │   └── 2024_06_01_exposure_100ms_gain_10/   # date + condition naming
│   └── synthetic/
│       └── ...                    # auto-logged metadata per dataset
├── nns/                           # Neural network component code
│   ├── laser/
│   │   ├── cnn/
│   │   │   └── 3_layer_64_neurons/
│   │   └── transformer/
│   ├── magnetic_field/
│   └── atom/
├── models/                        # Complete forward propagation pipeline
│   ├── input/                     # Input layer, normalization, preprocessing
│   ├── photons/                   # Laser model, optical path, mechano-optical noise
│   ├── fields/                    # B/E field models, vector/scalar potentials
│   ├── atoms/                     # Oven model, ballistic diffraction, Lindblad solver
│   ├── output/                    # Fluorescence → camera plane, optics, noise, simulated camera
│   ├── loss.py                    # MSE, physics constraints, regularization, autocorrelation
│   ├── model.py                   # End-to-end model integrating all components
│   └── train.py                   # Training loop, validation, backprop, hyperparameter tuning
├── utils/
│   ├── visualization/             # Plotting and model performance visualizations
│   ├── data_processing/           # Normalization, missing values, train/val/test split
│   ├── model_evaluation/          # Performance metrics, evaluation visualizations
│   └── logging/                   # Training progress logging; universal dataset naming
├── gui/                           # PyQt6 interface; real-time predictions and experiment control
│                                  #   eventually merge with main ../app/ GUI
├── training/                      # Stored training data
├── notebooks/                     # Per-component tutorials: examples, visualizations, benchmarks
├── tests/                         # Benchmarking code, metrics, comparisons to theory
├── docs/                          # Sphinx-generated API references and tutorials
├── main.py                        # Top-level training/evaluation script with CLI
├── requirements.txt
└── README.md
```
