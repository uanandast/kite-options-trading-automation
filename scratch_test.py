import time
import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize_scalar, brentq

N = norm.cdf

def BS_CALL(S, K, T, r, sigma):
    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * N(d1) - K * np.exp(-r * T) * N(d2)

def implied_vol_old(opt_value, S, K, T, r, type_='call'):
    def call_obj(sigma):
        return abs(BS_CALL(S, K, T, r, sigma) - opt_value)
    return minimize_scalar(call_obj, bounds=(0.01, 3), method='bounded').x

def implied_vol_new(opt_value, S, K, T, r, type_='call'):
    def call_root(sigma):
        return BS_CALL(S, K, T, r, sigma) - opt_value
    try:
        return brentq(call_root, 0.001, 5.0)
    except ValueError:
        return np.nan

# test params
S = 100
K = 100
T = 30/365
r = 0.08
opt_value = 5.0

start = time.time()
for _ in range(400):
    implied_vol_old(opt_value, S, K, T, r)
print("Old:", time.time() - start)

start = time.time()
for _ in range(400):
    implied_vol_new(opt_value, S, K, T, r)
print("New:", time.time() - start)

