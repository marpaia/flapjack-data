"""Direct-method exproession-rate inference, ported from wellFARe's one-step estimators.

https://www.youtube.com/watch?v=PAAkCSZUG1c&t=9m28s

Source: ibis-inria/wellFARe (``wellfare.ILM.onestep_estimators`` and ``wellfare.ILM.methods``).
The model is the linear inverse problem ``dF/dt = s(t)·V(t) − degr·F`` (synthesis) and
``dV/dt = mu(t)·V`` (growth): build the observation matrix ``H`` directly, then solve for the
control with a smoothness penalty whose strength ``alpha`` is chosen by generalized
cross-validation (GCV).

wellFARe's positive-solution branch uses cvxopt for a constrained quadratic program. Here the
same regularized non-negative objective ``min ‖Hx − y‖² + α‖Lx‖²  s.t.  x ≥ 0`` is solved with
SciPy's bounded least squares on the augmented system, so the only dependencies are numpy/scipy.
"""

from __future__ import annotations

import numpy as np
from scipy.integrate import odeint
from scipy.optimize import lsq_linear

#: Regularization strengths searched by GCV.
DEFAULT_ALPHAS = np.logspace(-10, 10, 1000)


class Curve:
    """A piecewise-linear, extrapolating callable through sampled points ``(x, y)``."""

    def __init__(self, x, y):
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)

    def __call__(self, t):
        return np.interp(t, self.x, self.y)

    def xlim(self):
        return self.x.min(), self.x.max()


def make_iL(Nu, Nic, eps=1e-4):
    """Inverse of a derivation matrix (integration operator) with ``Nic`` initial conditions."""
    ar = np.arange(Nu)
    iLu = 1.0 * ((ar - np.array([ar]).T) <= 0)
    iLu[:, 0] = 1.0 / eps
    if Nic == 0:
        return iLu
    iLic = (1.0 / eps) * np.identity(Nic)
    void = np.zeros((Nu, Nic))
    return np.vstack([np.hstack([iLic, void.T]), np.hstack([void, iLu])])


def make_L(Nu, Nic, eps_L=1e-3):
    """Derivation matrix (smoothness penalty) with ``Nic`` initial conditions."""
    L = np.identity(Nu + Nic)
    for i in range(Nic + 1):
        L[i, i] = eps_L
    for i in range(Nic, Nu + Nic - 1):
        L[i + 1, i] = -1
    return L


def gcv(y, H, alphas, Qv):
    """Generalized cross-validation: pick alpha minimizing leave-one-out error."""
    Q, vv = Qv
    Q2 = Q**2
    Qy = Q.T.dot(y)
    alphas = [a for a in alphas if (-a) not in vv]

    def gy(alpha):
        return Q.dot(Qy.T / (vv + alpha))

    def diag_g(alpha):
        return ((1.0 / (vv + alpha)) * Q2).sum(axis=-1)

    def looe(alpha):
        errs = gy(alpha) / diag_g(alpha)
        return (errs**2).mean()

    scores = [looe(a) for a in alphas]
    return alphas[int(np.argmin(scores))], scores


def infer_control(H, y, Nic, alphas=None, eps_L=1e-4, positive_solution=False):
    """Infer a control profile from observation matrix ``H`` with a smoothness penalty.

    Returns ``(u, y_smoothed, ic, alpha, scores)`` where ``u`` is the inferred control.
    """
    if alphas is None:
        alphas = DEFAULT_ALPHAS
    _, Nuic = H.shape
    iL = make_iL(Nuic - Nic, Nic, eps=eps_L)
    HiL = H.dot(iL)
    vv, Q = np.linalg.eigh(HiL.dot(HiL.T))

    if positive_solution:
        alpha, scores = gcv(y, HiL, alphas, Qv=(Q, vv))
        K = make_L(Nuic - Nic, Nic, eps_L=eps_L)
        augmented = np.vstack([H, np.sqrt(alpha) * K])
        target = np.concatenate([y, np.zeros(K.shape[0])])
        result = lsq_linear(augmented, target, bounds=(0, np.inf)).x
        ic, uu = result[:Nic], result[Nic:]
        return uu, H.dot(result), ic, alpha, scores

    alpha, scores = gcv(y, HiL, alphas, Qv=(Q, vv))
    K_ = HiL.T.dot(HiL)
    for i in range(len(K_)):
        K_[i, i] += alpha
    iLiK = iL.dot(np.linalg.inv(K_)).dot(HiL.T)
    uu = iLiK.dot(y)
    ic, u = uu[:Nic], uu[Nic:]
    return u, H.dot(uu), ic, alpha, scores


def infer_growth_rate(curve_v, ttu, alphas=None, eps_L=1e-4, positive=False):
    """Infer a growth-rate profile (a :class:`Curve`) from a biomass curve."""
    ttv = curve_v.x
    dttu = 1.0 * (ttu[1] - ttu[0])
    H_ic = np.ones((len(ttv), 1))
    dT = np.array([ttv]).T - ttu
    H_u = np.maximum(0, np.minimum(dttu, dT)) * curve_v(ttu + dttu / 2)
    H = np.hstack([H_ic, H_u])
    growth_rate, _, _, _, _ = infer_control(
        H, y=curve_v.y, Nic=1, alphas=alphas, eps_L=eps_L, positive_solution=positive
    )
    return Curve(ttu, growth_rate)


def infer_synthesis_rate_onestep(curve_f, curve_v, ttu, degr, alphas=None, eps_L=1e-4, positive=False):
    """Infer a synthesis-rate profile (a :class:`Curve`) from fluorescence and biomass curves."""
    tt_fluo = curve_f.x
    H_ic = np.exp(-degr * tt_fluo).reshape((len(tt_fluo), 1))

    def model(Y, t):
        return 1 - degr * Y

    dtau = ttu[1] - ttu[0]
    m = odeint(model, 0, [0, dtau]).flatten()[1]
    TT = ttu - np.array([tt_fluo]).T
    H_u = (m * np.exp(degr * TT) * (TT < 0)) * curve_v(ttu + 0.5 * dtau)
    H = np.hstack([H_ic, H_u])
    activity, _, _, _, _ = infer_control(H, y=curve_f.y, Nic=1, alphas=alphas, eps_L=eps_L, positive_solution=positive)
    return Curve(ttu, activity)
