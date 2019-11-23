#!/bin/python
# -*- coding: utf-8 -*-

import numpy as np
import numpy.linalg as nl
from scipy.optimize import minimize as so_minimize
from grgrlib.core import tinv
from numba import njit
from .stats import logpdf


class TEnKF(object):

    name = 'TEnKF'

    def __init__(self, N, dim_x=None, dim_z=None, fx=None, hx=None, rule=None, seed=None):

        self._dim_x = dim_x
        self._dim_z = dim_z
        self.t_func = fx
        self.o_func = hx

        self.N = N
        self.seed = seed

        self.R = np.eye(self._dim_z)
        self.Q = np.eye(self._dim_x)
        self.P = np.eye(self._dim_x)

        self.x = np.zeros(self._dim_x)
 
        try:
            import chaospy

            def multivariate(mean, cov, size):
                # rule must be of 'L', 'M', 'H', 'K' or 'S'
                res = chaospy.MvNormal(mean, cov).sample(size=size, rule=rule or 'L')
                res = np.moveaxis(res, 0, res.ndim-1) 
                np.random.shuffle(res)
                return res

        except ModuleNotFoundError as e:
            print(str(e)+". Low-discrepancy series will not be used. This is likely to cause a loss in precision.")
            def multivariate(mean, cov, size):
                return np.random.multivariate_normal(mean=mean, cov=cov, size=size)

        self.multivariate = multivariate


    def batch_filter(self, Z, init_states=None, seed=None, store=False, calc_ll=False, verbose=False):
        """Batch filter.

        Runs the TEnKF on the complete dataset.
        """

        # store time series for later
        self.Z = Z

        _dim_x, _dim_z, N, P, R, Q = self._dim_x, self._dim_z, self.N, self.P, self.R, self.Q

        I1 = np.ones(N)
        I2 = np.eye(N) - np.outer(I1, I1)/N

        if store:
            self.Xs = np.empty((Z.shape[0], _dim_x, N))
            self.X_priors = np.empty_like(self.Xs)
            self.X_bars = np.empty_like(self.Xs)
            self.X_bar_priors = np.empty_like(self.Xs)

        ll = 0

        if seed or self.seed:
            np.random.seed(seed or self.seed)

        means = np.empty((Z.shape[0], _dim_x))
        covs = np.empty((Z.shape[0], _dim_x, _dim_x))
        Y = np.empty((_dim_z, N))

        mus = self.multivariate(mean=np.zeros(self._dim_z), cov=self.R, size=(len(Z), self.N))
        epss = self.multivariate(mean=np.zeros(self._dim_z), cov=self.Q, size=(len(Z), self.N))
        X = init_states or self.multivariate(mean=self.x, cov=P, size=N).T

        self.Xs = np.empty((Z.shape[0], _dim_x, N))

        for nz, z in enumerate(Z):

            # predict
            for i in range(X.shape[1]):
                eps = epss[nz, i]
                X[:, i] = self.t_func(X[:, i], eps)[0]

            Y = self.o_func(X.T).T

            if store:
                self.X_priors[nz, :, :] = X

            # update
            X_bar = X @ I2
            Y_bar = Y @ I2
            ZZ = np.outer(z, I1)
            S = np.cov(Y) + R
            X += X_bar @ Y_bar.T @ nl.inv((N-1)*S) @ (ZZ - Y - mus[nz].T)

            if store:
                self.X_bar_priors[nz, :, :] = X_bar
                self.X_bars[nz, :, :] = X @ I2
                self.Xs[nz, :, :] = X

            if calc_ll:
                # cummulate ll
                z_mean = np.mean(Y, axis=1)
                y = z - z_mean
                ll += logpdf(x=y, mean=np.zeros(_dim_z), cov=S)
            else:
                self.Xs[nz, :, :] = X

        if calc_ll:
            self.ll = ll
            return ll
        else:
            return np.rollaxis(self.Xs, 2)

    def rts_smoother(self, means=None, covs=None, rcond=1e-14):

        S = self.Xs[-1]
        Ss = self.Xs.copy()

        for i in reversed(range(self.Xs.shape[0] - 1)):

            J = self.X_bars[i] @ tinv(self.X_bar_priors[i+1])
            S = self.Xs[i] + J @ (S - self.X_priors[i+1])

            Ss[i,:,:] = S

        self.Ss = Ss

        return np.rollaxis(Ss, 2)
