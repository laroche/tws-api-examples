import math
import numpy as np
from scipy.stats import norm


def black_scholes(S, K, r, T, sigma, option_type):
    d1 = (np.log(S/K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = (np.log(S/K) + (r - 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    if option_type == 'call':
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def black_scholes_delta(S, K, r, sigma, T, option_type):
    d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma * math.sqrt(T))
    delta = norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1
    return delta


def black_scholes_theta(S, K, r, sigma, T, option_type, position):
    d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    N_d2 = norm.cdf(d2)
    theta = -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * N_d2 if option_type == "call" else \
            (S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * (1 - N_d2)
    return theta * (-1 if position == "long" else 1)


def black_scholes_gamma(S, K, r, sigma, T, position):
    d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma * math.sqrt(T))
    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
    return gamma * (1 if position == "long" else -1)


def black_scholes_vega(S, K, r, sigma, T, position):
    d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma * math.sqrt(T))
    vega = S * norm.pdf(d1) * math.sqrt(T)
    return vega * (1 if position == "long" else -1)


def black_scholes_rho(S, K, r, sigma, T, option_type, position):
    d2 = (math.log(S/K) + (r - sigma**2/2)*T) / (sigma * math.sqrt(T))
    if option_type == "call":
        rho = K * T * math.exp(-r * T) * norm.cdf(d2)
        return rho * (1 if position == "long" else -1)
    elif option_type == "put":
        rho = -K * T * math.exp(-r * T) * norm.cdf(-d2)
        return rho * (1 if position == "short" else -1)

'''
The following example numbers can be replaced with streaming or import data
'''
# Example
S = 4               # stock price
K = 5               # strike price
r = 0.0459          # risk free rate (FRED: DTB3)
T = 30 / 365        # days to expiration
sigma = 0.901       # implied volatility
option_type = 'put' # option type (call/put)
position = 'short'  # position direction (long/short)

option_price = black_scholes(S, K, r, T, sigma, option_type)
print("Option Price: ${:.2f}".format(option_price))

delta_value = black_scholes_delta(S, K, r, sigma, T, option_type)
print("Option Delta: {:.2f}".format(delta_value))

theta_value = black_scholes_theta(S, K, r, sigma, T, option_type, position)
print("Option Theta: {:.2f}".format(theta_value))

gamma_value = black_scholes_gamma(S, K, r, sigma, T, position)
print("Option Gamma: {:.2f}".format(gamma_value))

vega_value = black_scholes_vega(S, K, r, sigma, T, position)
print("Option Vega: {:.2f}".format(vega_value))

rho_value = black_scholes_rho(S, K, r, sigma, T, option_type, position)
print("Option Rho: {:.2f}".format(rho_value))
