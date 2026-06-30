"""Inverse-method expression-rate inference.

Recovers a synthesis-rate (or growth-rate) profile from a fluorescence (or biomass) time series
by fitting a sum of Gaussians through a forward model and regularizing the Gaussian heights
(Tikhonov). This is Flapjack's self-contained alternative to the wellFARe-based direct method and
needs only numpy/scipy.

The forward model for synthesis is ``dp/dt = od(t)·profile(t) − gamma·p`` and for growth is
``dod/dt = mu(t)·od``; in both cases ``profile``/``mu`` is the Gaussian sum whose heights are
solved for by least squares.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import least_squares


def _forward_model(dt, odval, profile, gamma, p0, nt, sim_steps=10):
    p1_list = []
    p1 = p0
    for t in range(nt):
        p1_list.append(p1)
        for _ in range(sim_steps):
            p1 = p1 + (odval[t] * profile[t] - gamma * p1) * dt / sim_steps
    return np.array(p1_list)


def _gaussian_sum(t, means, variances, heights):
    profile = np.zeros_like(t, dtype=float)
    for mean, var, height in zip(means, variances, heights):
        profile = profile + height * np.exp(-(t - mean) * (t - mean) / var / 2) / np.sqrt(2 * np.pi * var)
    return profile


def _residuals(data, odval, dt, t, n_gaussians, epsilon, gamma):
    means = np.linspace(t.min(), t.max(), n_gaussians)
    variances = [(t.max() - t.min()) / n_gaussians] * n_gaussians

    def func(x):
        p0 = x[0]
        heights = x[1:]
        profile = _gaussian_sum(t, means, variances, heights)
        model = _forward_model(dt, odval, profile, gamma, p0, len(t))[1:]
        residual = data[1:] - model
        tikhonov = heights * epsilon
        return np.concatenate((residual, tikhonov))

    return func


def characterize(expression, biomass, t, gamma, n_gaussians, epsilon):
    """Infer a synthesis-rate profile (callable of time) from expression and biomass curves."""
    dt = np.diff(t).mean()
    bounds = ([0] + [0] * n_gaussians, [1e8] + [1e8] * n_gaussians)
    res = least_squares(
        _residuals(expression, biomass, dt, t, n_gaussians, epsilon, gamma),
        [0] + [100] * n_gaussians,
        bounds=bounds,
    )
    means = np.linspace(t.min(), t.max(), n_gaussians)
    variances = [(t.max() - t.min()) / n_gaussians] * n_gaussians
    profile = _gaussian_sum(t, means, variances, res.x[1:])
    return interp1d(t, profile, fill_value="extrapolate", bounds_error=False)


def _forward_model_growth(dt, muval, od0, nt, sim_steps=10):
    od_list = []
    od = od0
    for t in range(nt):
        od_list.append(od)
        for _ in range(sim_steps):
            od = od + muval[t] * od * dt / sim_steps
    return np.array(od_list)


def _residuals_growth(data, epsilon, dt, t, n_gaussians):
    means = np.linspace(t.min(), t.max(), n_gaussians)
    variances = [(t.max() - t.min()) / n_gaussians] * n_gaussians

    def func(x):
        od0 = x[0]
        muval = _gaussian_sum(t, means, variances, x[1:])
        model = _forward_model_growth(dt, muval, od0, len(t))
        residual = data - model
        return np.concatenate((residual, epsilon * x[1:]))

    return func


def characterize_growth(biomass, t, n_gaussians, epsilon):
    """Infer a growth-rate profile (callable of time) from a biomass curve."""
    dt = np.mean(np.diff(t))
    bounds = ([0] + [0] * n_gaussians, [100] + [50] * n_gaussians)
    res = least_squares(
        _residuals_growth(biomass, epsilon, dt, t, n_gaussians),
        [0.01] + [1] * n_gaussians,
        bounds=bounds,
    )
    means = np.linspace(t.min(), t.max(), n_gaussians)
    variances = [(t.max() - t.min()) / n_gaussians] * n_gaussians
    profile = _gaussian_sum(t, means, variances, res.x[1:])
    return interp1d(t, profile, fill_value="extrapolate", bounds_error=False)
