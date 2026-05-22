# simulation/

Physics simulation for the Yb magnetometer experiment.

## ATSolver.py

Solves the Lindblad (GKSL) master equation for a 4-level Yb system using QuTiP's `mesolve`. Models:

- Doppler averaging over Maxwell-Boltzmann velocity distribution
- B-field Zeeman shifts (static and dynamic)
- Multiple light fields / laser polarization angles
- Atom-laser coupling and fluorescence emission

Originally written by Tanaporn Na Narong (2023); reformatted with type annotations by Ben Kroul.

**Requires:** `qutip` — install separately via `uv pip install qutip` or `pip install qutip`.

See `ATSolver_test.ipynb` for worked usage examples.

## Relationship to torch/

The [`torch/`](../torch/README.md) ML pipeline is building a differentiable PyTorch replacement/supplement for `ATSolver.py` — targeting faster inference and gradient-based parameter fitting. `ATSolver.py` serves as the ground-truth reference for benchmarking the PyTorch model.
