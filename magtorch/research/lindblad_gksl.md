# Differentiable Lindblad (GKSL) Master Equation

> Research notes for `magtorch/models/atoms/`. Implementation: native PyTorch (~50 lines) + `torchdiffeq` for time-dependent H.

---

## 1. The GKSL Equation

$$
\boxed{
  \dot\rho = -\frac{i}{\hbar}[H,\rho]
  + \sum_k \Gamma_k \mathcal{D}[L_k]\rho
}
\qquad
\mathcal{D}[L]\rho = L\rho L^\dagger - \tfrac{1}{2}L^\dagger L\,\rho - \tfrac{1}{2}\rho\,L^\dagger L
$$

| Symbol | Meaning |
|--------|---------|
| $\rho \in \mathbb{C}^{n\times n}$ | Density matrix; Hermitian, $\rho\ge 0$, $\text{Tr}[\rho]=1$ |
| $L_k$ | Jump operator for channel $k$ |
| $\Gamma_k$ | Decay rate for channel $k$ (rad/s) |

Most general Markovian, trace-preserving, completely-positive evolution. Validity for Yb: photon vacuum $\tau_c \to 0 \ll$ atomic coherence times ($\mu$s–ms). Conservation ($\text{Tr}[\rho]=1$, $\rho\ge 0$, Hermiticity) is enforced analytically by the Lindblad form — violation in numerics signals step-size or sign errors.

**Derivation path:** Born (weak coupling) → Markov (short $\tau_c$) → secular (RWA) → trace over vacuum → GKSL.

---

## 2. Fock–Liouville Superoperator Formulation

Column-stack $\rho$ into $|\rho\rangle\!\rangle = \text{vec}(\rho) \in \mathbb{C}^{n^2}$:

$$
\frac{d}{dt}|\rho\rangle\!\rangle = \mathcal{L}\,|\rho\rangle\!\rangle
$$

$$
\mathcal{L}
  = -\frac{i}{\hbar}(H\otimes I - I\otimes H^T)
  + \sum_k \Gamma_k\!\left(L_k\otimes L_k^*
    - \tfrac{1}{2}I\otimes L_k^\dagger L_k
    - \tfrac{1}{2}(L_k^\dagger L_k)^T\otimes I\right)
$$

For Yb ($n=4$): $\mathcal{L}$ is $16\times 16$. Even $n=10$ (extended hyperfine) gives $100\times 100$ — trivially small.

| Property | Direct $n\times n$ ODE | Superoperator |
|----------|----------------------|----------------|
| Time-independent $H$ | must integrate step-by-step | $\rho(t) = e^{\mathcal{L}t}\rho(0)$ exact |
| Steady state | integrate to convergence | null-space of $\mathcal{L}$ |
| Batching over $\vec B$ | independent RK steps per sample | batched matmul |

**Static-H solver (~20 lines):**

```python
import torch

def liouvillian(H: torch.Tensor, L_ops: list, rates: list) -> torch.Tensor:
    n  = H.shape[-1]
    I  = torch.eye(n, dtype=H.dtype, device=H.device)
    Lv = -1j * (torch.kron(H, I) - torch.kron(I, H.mT.conj()))
    for Lk, gk in zip(L_ops, rates):
        LdL = Lk.mH @ Lk
        Lv += gk * (torch.kron(Lk, Lk.conj())
                    - 0.5 * torch.kron(I, LdL)
                    - 0.5 * torch.kron(LdL.mT, I))
    return Lv  # (n², n²)

def mesolve_static(H, L_ops, rates, rho0, t_eval):
    Lv = liouvillian(H, L_ops, rates)
    rho_vec0 = rho0.reshape(-1)
    return torch.stack([
        (torch.linalg.matrix_exp(Lv * t) @ rho_vec0).reshape(rho0.shape)
        for t in t_eval
    ])  # (T, n, n)
```

**Time-dependent H** (pulser, AM modulation) — use `torchdiffeq`:

```python
from torchdiffeq import odeint_adjoint as odeint

def drho_dt(t, rho_vec):
    Lv = liouvillian(H0 + field(t) * H1, L_ops, rates)
    return Lv @ rho_vec

rho_t = odeint(drho_dt, rho0.reshape(-1), t_eval,
               method='dopri5', adjoint_params=params)
```

The adjoint method computes gradients in $O(1)$ memory by solving the adjoint ODE backward — critical for long stroboscopic sequences.

---

## 3. Differentiability

Gradient chain: $\vec B \to H_Z \to H \to \mathcal{L} \to \rho(t) \to F(t) \to I_\text{pred} \to \mathcal{L}_\text{MSE}$.

| Operation | Autograd | Notes |
|-----------|----------|-------|
| `torch.linalg.matrix_exp` | ✅ | Padé approximant; fully differentiable |
| `torch.kron` | ✅ | |
| `torchdiffeq.odeint_adjoint` | ✅ | $O(1)$ memory backprop |
| `torch.linalg.solve` | ✅ | steady-state via null-space |

**Precision:** use `torch.complex128` during development; validate against QuTiP before switching to `complex64`. Optionally re-symmetrize after long sequences:

```python
rho = (rho + rho.conj().mT) / 2
rho = rho / rho.diagonal(dim1=-2, dim2=-1).sum(-1, keepdim=True).unsqueeze(-1)
```

---

## 4. YbMag Hamiltonian

**Transition:** $^1\!S_0\,(J=0) \leftrightarrow\ ^3\!P_1\,(J=1)$, $\lambda \approx 556$ nm, $\tau = 875$ ns, $\Gamma = 1/\tau \approx 1.14\times 10^6$ rad/s.

**Basis:** $\{|g\rangle,|e_{-1}\rangle,|e_0\rangle,|e_{+1}\rangle\}$, $n=4$.

> Fermionic isotopes (¹⁷¹Yb: $I=1/2$; ¹⁷³Yb: $I=5/2$) add hyperfine structure ($n=8$ or $28$); solver is otherwise unchanged.

**Zeeman** ($g_J = 1.493$ for ³P₁, embedded in excited-state $3\times3$ block):

$$
H_Z = g_J\mu_B(\vec J \cdot \vec B),\quad
J_z = \begin{pmatrix}-1&0&0\\0&0&0\\0&0&1\end{pmatrix},\quad
J_x = \frac{1}{\sqrt{2}}\begin{pmatrix}0&1&0\\1&0&1\\0&1&0\end{pmatrix},\quad
J_y = \frac{i}{\sqrt{2}}\begin{pmatrix}0&-1&0\\1&0&-1\\0&1&0\end{pmatrix}
$$

**Atom-laser coupling** (RWA, detuning $\Delta = \omega_L - \omega_0$, linear polarization angle $\chi$):

$$
H_{AL} = \hbar\begin{pmatrix}0 & \Omega_{-1}^* & \Omega_0^* & \Omega_{+1}^*\\ \Omega_{-1} & \Delta & 0 & 0\\ \Omega_0 & 0 & \Delta & 0\\ \Omega_{+1} & 0 & 0 & \Delta\end{pmatrix},\quad
\Omega_{\pm1} = \mp\frac{\Omega\sin\chi}{\sqrt2},\quad \Omega_0 = \Omega\cos\chi
$$

**Jump operators** (each excited sublevel decays to $|g\rangle$ at rate $\Gamma$):

$$
L_q = \sqrt\Gamma\,|g\rangle\langle e_q|,\quad q\in\{-1,0,+1\}
$$

```python
def yb_jump_operators(gamma: float, device='cpu') -> list:
    ops = []
    for i in range(1, 4):
        L = torch.zeros(4, 4, dtype=torch.complex128, device=device)
        L[0, i] = gamma**0.5
        ops.append(L)
    return ops
```

**Fluorescence observable:**

$$
F(t) = \Gamma\,\text{Tr}[\Pi_e\,\rho(t)],\quad \Pi_e = \text{diag}(0,1,1,1)
$$

```python
F = gamma * rho_t[..., 1:, 1:].diagonal(dim1=-2, dim2=-1).sum(-1).real
```

**Doppler averaging** — Maxwell-Boltzmann $f(v_z)\propto e^{-mv_z^2/2k_BT}$ shifts detuning by $\Delta(v_z) = \Delta_0 - k_L v_z$; integrate incoherently over velocity classes via Gauss-Hermite quadrature (8–16 nodes):

$$
F_\text{obs}(t) \approx \sum_j w_j\, F(\Delta(v_{z,j}),\, t)
$$

**Batch structure:** `(N_B, N_vclass, N_t, n, n)` — `torch.vmap` or explicit batch dims over $\vec B$ and $v_z$.

---

## 5. Implementation Plan

| Phase | Task |
|-------|------|
| 1 | `liouvillian`, `mesolve_static` in `models/atoms/lindblad.py`; `yb_hamiltonian`, `yb_jump_operators`, `fluorescence` |
| 1 | Benchmark vs. QuTiP `mesolve` on 100 random $\vec B$ samples; assert $<10^{-6}$ relative error |
| 2 | `mesolve_td` via `torchdiffeq`; test time-varying $B_z(t)$ vs. QuTiP |
| 3 | Vectorize `liouvillian` over batch dims; `doppler_average` via Gauss-Hermite; profile GPU |
| 4 | Validate $\partial F/\partial B_z$ autograd vs. finite difference; confirm adjoint == direct backprop |

---

## 6. Minimum Working Example

```python
"""Minimal differentiable GKSL solver for Yb ¹S₀ ↔ ³P₁."""
import torch

GAMMA = 1 / 875e-9
GJ    = 1.493
MU_B  = 9.2740100783e-24

def liouvillian(H, L_ops, rates):
    n  = H.shape[-1]
    I  = torch.eye(n, dtype=H.dtype, device=H.device)
    Lv = -1j * (torch.kron(H, I) - torch.kron(I, H.mT.conj()))
    for Lk, gk in zip(L_ops, rates):
        LdL = Lk.mH @ Lk
        Lv += gk * (torch.kron(Lk, Lk.conj())
                    - 0.5 * torch.kron(I, LdL)
                    - 0.5 * torch.kron(LdL.mT, I))
    return Lv

def yb_hamiltonian(B, Omega, chi, Delta=0.0):
    device, dtype = B.device, B.dtype
    sq2 = 2**0.5
    Jx = torch.tensor([[0,1,0],[1,0,1],[0,1,0]], dtype=dtype, device=device) / sq2
    Jy = torch.tensor([[0,-1j,0],[1j,0,-1j],[0,1j,0]], dtype=dtype, device=device) / sq2
    Jz = torch.diag(torch.tensor([-1.,0.,1.], dtype=dtype, device=device))
    H_ee = GJ * MU_B * (B[0]*Jx + B[1]*Jy + B[2]*Jz)
    H = torch.zeros(4, 4, dtype=dtype, device=device)
    H[1:, 1:] = H_ee + Delta * torch.eye(3, dtype=dtype, device=device)
    Om = [Omega * torch.sin(torch.tensor(chi)) / sq2,
          Omega * torch.cos(torch.tensor(chi)),
         -Omega * torch.sin(torch.tensor(chi)) / sq2]
    for i, Om_q in enumerate(Om, 1):
        H[0, i] = Om_q / 2;  H[i, 0] = Om_q / 2
    return H

if __name__ == "__main__":
    B    = torch.tensor([0., 0., 1e-6], requires_grad=True)
    H    = yb_hamiltonian(B.to(torch.complex128), Omega=2*3.14159*1e4, chi=0.)
    Lops = [torch.zeros(4,4,dtype=torch.complex128) for _ in range(3)]
    for i in range(3): Lops[i][0, i+1] = GAMMA**0.5
    Lv   = liouvillian(H, Lops, [1.0]*3)
    rho0 = torch.zeros(4, 4, dtype=torch.complex128); rho0[0,0] = 1.0
    t_eval = torch.linspace(0, 5/GAMMA, 200)
    rho_t = torch.stack([
        (torch.linalg.matrix_exp(Lv * t) @ rho0.reshape(-1)).reshape(4,4)
        for t in t_eval
    ])
    F = GAMMA * rho_t[:, 1:, 1:].diagonal(dim1=-2, dim2=-1).sum(-1).real
    F.sum().backward()
    print("dF/dB_z:", B.grad[2].item())
```

---

## 7. Library Comparison

Native PyTorch is the chosen implementation. For context:

| Library | Backend | Differentiable | Stars | Notes |
|---------|---------|---------------|-------|-------|
| **Native PyTorch** *(chosen)* | PyTorch | ✅ `matrix_exp` + `torchdiffeq` | — | ~50 lines; pure PyTorch; no wrapper types; native batch/vmap |
| **dynamiqs** | PyTorch + JAX | ✅ adjoint built-in | ~1k | Best third-party option; `dq.mesolve` accepts raw tensors; JAX adds a dual-framework dependency |
| **torchqc** | PyTorch | ✅ | 10 | Coupled to `Operator`/`QuantumState` wrappers; no batched density matrices; MIT license |
| **torchdiffeq** | PyTorch | ✅ adjoint | ~5k | ODE solver only — used here for time-dependent H |
| **QuTiP 5** | NumPy/SciPy | ❌ | ★★★★★ | Benchmarking reference only; no autograd |

---

## References

- Gorini, Kossakowski, Sudarshan (1976). *J. Math. Phys.* 17, 821.
- Lindblad (1976). *Commun. Math. Phys.* 48, 119.
- Breuer & Petruccione, *The Theory of Open Quantum Systems* (2002).
- torchdiffeq: <https://github.com/rtqichen/torchdiffeq> (MIT)
- dynamiqs: <https://dynamiqs.org> (MIT)
- Chen et al., "Neural ODEs", NeurIPS 2018.
