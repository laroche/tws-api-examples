#!/usr/bin/env python3
#
# Copyright (C) 2023,2026 Florian La Roche <Florian.LaRoche@gmail.com>
#
# Tested on Debian. (Should run fine on Ubuntu and any other Linux.)
#
# Installation/preparation:
# sudo apt-get install python3-venv python3-rich python3-pandas
# python3 -m venv venv
# . venv/bin/activate
# pip3 install ib_async
# pip3 install rich
# ./ib-info.py
# ./ib-info.py -m
#
# Configuration of IB TWS Java memory usage:
# ~/Jts/tws.vmoptions:
# -Xmx4096m
#
# Use one of the following ports:
# - port 7496: TWS active/real/live account
# - port 7497: TWS paper account (demo/test)
# - port 4001: IB Gateway (IBG) active/real/live account
# - port 4002: IB Gateway (IBG) paper account (demo/test)
# The client id must be unique per connection/client:
# - client_id 0 is getting all transactions, including also TWS.
# - client_id 1 (configurable) is getting transactions from other client_ids, but not TWS.
# Even if market data is available for TWS, the API might not get market data
# as well. Check the market data subscriptions (for your country) in detail.
# Using subscription data is disabled by default, use param '-m' to enable
# using market data subscriptions.
#
# TODO:
# - Make this also a web application.
# - Translate all prices into Euro (base currency) as an option.
# - Allow translation of output into different languages.
# - For currency overview futures are not yet included.
# - Allow for nice/modern config file.
# - We use local timzone. For DTE calculations we should use exchange timezone?
#   Also check ib_async.util.time_to_tws().
# - print() -> console.print()
# - Add to options output:
#   - delta, gamma, theta, vega values
#   - list notional value of all stock option short puts if assigned
#     Show also needed cash as percentage of all available cash.
#     Also account for spreads instead of naked puts.
#   - list all options < 21 DTE, maybe only if delta is above a certain value
#   - list all long options with DTE < 60(?) that should get rolled (hedges, Delta < 5)
#   - list all short options with delta > 40 that should get rolled
#     - calculate the best delta/time for rolling options by looking at current prices
#   - list all short call options not covered by stock
#   - list weighted average strike price for Put/Call Short Options per underlying
#   - grouping of complex (future) options, advise on next steps for strategies
#   - also add historical prices for options, also check other data sources
#   - If no market data is available, should we ask for historical data?
#   - for option prices, also check option equivalent prices as comparison
# - summary per contract type and underlying
# - Assets per currency overview: list all $/EUR-denominated assets.
# - New summary info with UnrealizedPnL would be nice. Not part of accountSummary.
# - overview pages markets
# - Warn if margin is above certain level. No new (option) positions above a certain level.
#   Close contracts above a certain level?
# - allow different sorting strategies for overview pages
# - Should large numbers use "." as thousand separator? Check en_US locale.
# - Output time of last data update from TWS into overview pages.
# - Allow refresh of portfolio overview data.
# - Add cash-like symbols to amount of optional cash: SGOV/BIL, US-T-Bills, TLT...
# - Warn about negative cash values.
# - Add automatic trading and advise on trading strategies.
# - If TWS is suspended (due to mobile app started), this script times out and hangs.
# - How to allow for re-connects?
# - Is a disconnect done properly for all error cases?
# - add sqlite database for historical data?
# - pi.marketValue, pi.averageCost, pi.marketPrice, ct.multiplier can be None
#
# pylint: disable=W0511,R0912,C0103,C0114,C0115,C0116
#

#from dataclasses import dataclass
from typing import Any
from functools import lru_cache
import sys
import os
import locale
import logging
import datetime
import argparse
import asyncio
from ib_async import (IB, FuturesOption, Option, AccountValue,
    PortfolioItem, Contract, Stock, Future, Forex, OptionComputation, util)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# How verbose should logging be?
# Check with params --verbose/-v, --debug, --quiet.
verbose: int = 1

# Output configuration:
# Limit year of expiration date to 2 digits only.
# This is param '--two-digit-years':
ShowYearWithTwoDigits: bool = False
# Do not show current year for expiration dates.
# This is param '--short-expire-format':
DoNotShowCurrentYear: bool = False

# Show a red margin above this margin level:
MarginRed: float = 50.0
# Show a yellow margin above this margin level:
MarginYellow: float = 30.0

# Futures and Futures-Options that are used for currency hedging
# and should be displayed within an extra overview page:
CURRENCY_SYMBOLS: set[str] = {'EUR', 'M6E', '6E'}

logger: logging.Logger = logging.getLogger(__name__)

# Keep track of 30 different messages and then warn again
@lru_cache(30)
def warn_once(mylogger: logging.Logger, msg: str) -> None:
    mylogger.warning(msg)

# Turn off some of the more annoying logging output from ib_async:
#logging.getLogger('ib_async.wrapper').setLevel(logging.CRITICAL)
#logging.getLogger('ib_async.ib').setLevel(logging.ERROR)

# Many subscriptions of market data are only available within the
# TWS, but not for the (python) API. So by default, we set
# access to market subscription data to False and delayed market data
# to True.
# Both can be changed with param --use-market-data/-m:
UseMarketDataSubscription: bool = False
# Use delayed market data instead of realtime data?
delayed_market_data: bool = True

# XXX How to detect base currency?
#BASE = '€'

#@dataclass
#class IBConfig: # AppConfig
#    host: str = '127.0.0.1'
#    port: int = 7496
#    client_id: int = 0
#    account: str = ''
#    readonly: bool = False
#    show_year_with_two_digits: bool = False
#    do_not_show_current_year: bool = False
#    verbose: int = 1
#
#    @classmethod
#    def from_env(cls) -> 'IBConfig':
#        """Load configuration from environment variables"""
#        return cls(
#            host=os.environ.get('IBKR_HOST', '127.0.0.1'),
#            port=int(os.environ.get('IBKR_PORT', 7496)),
#            # ... etc
#        )
#
#    @classmethod
#    def from_args(cls, args) -> 'AppConfig':
#        cfg = cls()
#        cfg.verbose = 3 if args.debug else (0 if args.quiet else args.verbose)
#        cfg.show_year_with_two_digits = bool(args.two_digit_years)
#        cfg.do_not_show_current_year = bool(args.short_expire_format)
#        if cfg.do_not_show_current_year:
#            cfg.current_year = datetime.date.today().strftime('%Y')
#        return cfg
#config = IBConfig()

#def readConfig(file_path):
#    import configparser
#    config = configparser.ConfigParser()
#    config.read(file_path)
#
#    ib_host = config.get('ib_connection', 'host')
#    ib_port = config.getint('ib_connection', 'port')
#    ib_client_id = config.getint('ib_connection', 'client_id')
#
#    log_level = config.get('logging', 'level').upper()
#    log_filename = config.get('logging', 'filename')
#    return config

# Convert currency name into short currency symbol:
currency_conversion: dict[str, str] = {
    'EUR': '€', 'USD': '$', 'GBP': '£', 'JPY': '¥'}

def get_currency_symbol(curr: str) -> str:
    return currency_conversion.get(curr, curr)

# Format a float output, smaller numbers get 4 decimals:
def format_float(f: float | None, curr: str) -> str:
    if f is None:
        return ''
    af = abs(f)
    if af < 10.0:
        return f'{f:.4f} {curr}'
    if af < 1000.0:
        return f'{f:.2f} {curr}'
    return f'{f:.0f} {curr}'

def print_data(value: float) -> str:
    #if value >= 980000:
    #    return locale.format_string('%d', round(value / 1000), grouping=True) + 'T'
    return locale.format_string('%d', round(value), grouping=True)
    #return f"{value:n}"

# Debugging output of accountSummary:
def printAccountSummary(accountSummary: list[AccountValue]) -> None:
    print()
    print('Account Summary:')
    for a in accountSummary:
        print(a)

# Extract key data from accountSummary:
def getAccountDetails(accounts: list[str], accountSummary: list[AccountValue]) -> list[tuple[str,
    str, float, str, str, str]]:
    ret = []
    for account in accounts:
        (nav, nav_str, cash, cash_str, margin, margin_str) = (0.0, '0', 0.0, '0', 0.0, '0')
        for p in accountSummary:
            if p.account != account:
                continue
            # XXX For account=='All' this needs changes: NetLiquidation is
            # NetLiquidationByCurrency with currency=BASE.
            # TotalCashBalance with BASE, no Cushion/margin.
            if p.tag == 'TotalCashValue':
                cash = float(p.value)
                cash_str = print_data(cash) + get_currency_symbol(p.currency)
            elif p.tag == 'Cushion':
                # Handle IBKR returning cushion as percentage (e.g., "95.2")
                cushion_val = float(p.value)
                #if cushion_val > 1.0:
                #    cushion_val /= 100.0
                margin = (1.0 - cushion_val) * 100.0
                margin_str = f'{margin:.1f}%'
            elif p.tag == 'NetLiquidation':
                nav = float(p.value)
                nav_str = print_data(nav) + get_currency_symbol(p.currency)
        cash_percent = f'{cash * 100.0 / nav:.0f}%' if nav > 0.0 else '0%'
        ret.append((account, nav_str, margin, margin_str, cash_str, cash_percent))
    return ret

# Display key data from accountSummary:
def showAccountSummary(console: Console, accounts: list[str],
    accountSummary: list[AccountValue]) -> None:
    if verbose >= 3:
        printAccountSummary(accountSummary)
    table = Table(title='Account Summary')
    if len(accounts) > 1:
        accounts = accounts.copy()
        accounts.append('All')
    table.add_column('Account')
    table.add_column('NetLiq', justify='right')
    table.add_column('Margin', justify='right')
    table.add_column('Cash', justify='right')
    #table.add_column('US-T: 120 T€ (7%)')
    #table.add_column('Sold Options: -100(12000) (0,05%)')
    #table.add_column('Stocks: 400 T€ (20%)')
    accountDetails = getAccountDetails(accounts, accountSummary)
    for (account, nav, margin, margin_str, cash, cash_percent) in accountDetails:
        # XXX add info on time of last update
        if account == 'All':
            table.add_section()
        if margin >= MarginRed:
            margin_str = f'[bold red]{margin_str}[/]'
        elif margin >= MarginYellow:
            margin_str = f'[yellow]{margin_str}[/]'
        table.add_row(f'{account}', f'{nav}', margin_str, f'{cash} ({cash_percent})')
    console.print(Panel(table))
    for (account, nav, margin, margin_str, cash, cash_percent) in accountDetails:
        if margin >= MarginRed:
            console.print(f"[bold red]Warning: Account {account} uses margin of {margin_str}.[/]")

# Store market price and greeks of instruments into a dictionary:
data_cache: dict[tuple[int, str], float] = {}
greeks_cache: dict[tuple[int, str], OptionComputation] = {}
#currency_prices: dict[str, float] = {}

def addMarketPrice(name: str, num: int, price: float) -> None:
    if (num, name) not in data_cache:
        data_cache[(num, name)] = price

def getMarketPrice(name: str, num: int) -> float | None:
    if (num, name) in data_cache:
        return data_cache[(num, name)]
    warn_once(logger,
        f'Not getting market price for {name}. ITM/theta calculations might be wrong.')
    return None

def getGreeksCache(name: str, num: int) -> OptionComputation | None:
    if (num, name) in greeks_cache:
        return greeks_cache[(num, name)]
    return None

# Strip ".0" at end of string:
def strip_decimal_zero(value: str) -> str:
    return value[:-2] if value.endswith('.0') else value
    #return f'{float(value):g}'

# Return position size as string:
def getPosition(pi: PortfolioItem) -> str:
    return strip_decimal_zero(f'{pi.position}')

# Return strike price as string:
def getStrike(contract: Contract) -> str:
    return strip_decimal_zero(f'{contract.strike}')

# Current year:
cur_year: str | None = None

# Return instrument name as string:
def getName(contract: Contract) -> str:
    if not isinstance(contract, (FuturesOption, Option)):
        return contract.localSymbol
    # Options require some more work for an instrument name:
    expiration = contract.lastTradeDateOrContractMonth
    if ShowYearWithTwoDigits:
        expiration = expiration[2:]
    elif DoNotShowCurrentYear:
        if cur_year == expiration[:4]:
            expiration = expiration[4:]
    return f'{contract.symbol} {contract.right}{getStrike(contract)} {expiration}'

def get_third_friday(yearmonth: str) -> str:
    """Return the day number of the third Friday in a given month and year."""
    first_day = datetime.date(int(yearmonth[:4]), int(yearmonth[4:]), 1)
    days_until_friday = (4 - first_day.weekday()) % 7
    third_friday = first_day + datetime.timedelta(days=days_until_friday + 14)
    return f'{third_friday.day:02d}'
    #return f'{pandas.tseries.offsets.Friday(3):02d}'

# Return DTE (Days Til Expiration) for an option/future:
#@lru_cache(maxsize=1024)
def getDTE(contract: Contract | None, expiration: str | None = None) -> int:
    if contract is not None:
        expiration = contract.lastTradeDateOrContractMonth
    if expiration is None:
        raise ValueError(f'No expiration date provided for contract {getName(contract)}')
        #XXX return -2
    if len(expiration) == 8:
        d = datetime.datetime.strptime(expiration, '%Y%m%d')
    elif len(expiration) == 6:
        logger.warning(f'Monthly expiration date without exact day: {expiration}.')
        # XXX Is it correct to look up the third friday of the month?
        # XXX fetch the exact expiration via ib.reqContractDetailsAsync(contract)
        third_friday = get_third_friday(expiration)
        d = datetime.datetime.strptime(expiration + third_friday, '%Y%m%d')
    else:
        logger.error('Wrong expiration date: %s.', expiration)
        raise ValueError(f'Expiration date ({expiration}) is unknown.')
    dte = d.date() - datetime.date.today()
    return dte.days

# Return average daily theta decay, DTE and underlying_price:
def getThetaDTE(pi: PortfolioItem, gr: OptionComputation | None) -> tuple[float, int, float | None]:
    ct = pi.contract
    dte = getDTE(ct)
    value = pi.marketValue # value = intrinsic + extrinsic
    if gr is not None and gr.undPrice is not None:
        underlying_price: float | None = gr.undPrice
        # Add price into our cache:
        if underlying_price is not None:
            num = 1 if isinstance(ct, Option) else 4
            addMarketPrice(ct.symbol, num, underlying_price)
    else:
        # Stock or Future?
        num = 1 if isinstance(ct, Option) else 4
        underlying_price = getMarketPrice(ct.symbol, num)
    if value is None:
        return (0.0, dte, underlying_price)
    # Prefer IB's model theta:
    if gr is not None and gr.theta is not None:
        daily_theta_decay = gr.theta * float(ct.multiplier) * pi.position
        return (daily_theta_decay, dte, underlying_price)
    # Compute theta decay ourselves:
    #oldvalue = value
    if underlying_price is not None:
        # subtract intrinsic value
        if ct.right == 'P' and underlying_price < ct.strike:
            value -= (ct.strike - underlying_price) * float(ct.multiplier) * pi.position
        if ct.right == 'C' and underlying_price > ct.strike:
            value -= (underlying_price - ct.strike) * float(ct.multiplier) * pi.position
    avg_daily_theta_decay = (- value) / (dte + 1) if dte >= 0 else 0.0
    #print(pi.position, getName(ct), oldvalue, value, dte, avg_daily_theta_decay)
    return (avg_daily_theta_decay, dte, underlying_price)

# Debug output of portfolio data:
def showPortfolioDebug(portfolio: list[PortfolioItem]) -> None:
    print()
    print('Portfolio:')
    for p in portfolio:
        print(p)

# Sum up values within individual portfolio items:
def accumulate_values(d: dict[str, list[float]], values: list[float] | tuple[float],
                      currency: str) -> None:
    """Generic accumulator for currency-keyed dictionaries."""
    # Check if we need to add a new currency:
    if currency not in d:
        d[currency] = [0.0] * len(values)
    # Add to all entries for this currency:
    for i, v in enumerate(values):
        d[currency][i] += v

def isITM(contract: Contract, underlying_price: float | None) -> bool:
    if underlying_price is None:
        return False
    if contract.right == 'P' and underlying_price <= contract.strike:
        return True
    if contract.right == 'C' and underlying_price >= contract.strike:
        return True
    return False

# Output a summary line for the portfolio (could be for the complete portfolio, or
# just a summary for one expiration date or for one underlying:
def add_summary(name: str, values: list[float], curr: str, show_options_details: bool,
                show_prices: bool, table: Table,
                underlying_price: str, expiration: str | None) -> None:
    (sum_costbasis, sum_marketValue, sum_theta, sum_delta_curr) = values
    pnl = sum_marketValue - sum_costbasis
    pnl_percent = (pnl / abs(sum_costbasis)) * 100.0 if sum_costbasis != 0.0 else 0.0
    row = ['', name, f'{pnl:.0f} {curr}', f'{pnl_percent:.1f}%',
           f'{sum_marketValue:.0f} {curr}', f'{sum_costbasis:.0f} {curr}']
    if show_prices:
        row.extend(['', ''])
    if show_options_details:
        dte = getDTE(None, expiration) if expiration is not None else ''
        row.extend([f'{dte}', f'{sum_theta:.2f} {curr}', underlying_price, ''])
        if UseMarketDataSubscription:
            sum_delta_curr_str = ''
            if sum_delta_curr != 0.0:
                sum_delta_curr_str = f'{sum_delta_curr:.0f} {curr}'
            row.extend(['', '', sum_delta_curr_str, '', ''])
    table.add_row(*row)

def getDataCacheNum(contract: Contract) -> int:
    if isinstance(contract, Stock):
        return 1
    if isinstance(contract, Option):
        return 2
    if isinstance(contract, FuturesOption):
        return 3
    if isinstance(contract, Future):
        return 4
    if isinstance(contract, Forex):
        return 5
    return 0

async def getPortfolioData(ib: IB, portfolio: list[PortfolioItem]) -> None:
    cache: dict[tuple[int, str], bool] = {}
    # collect existing stock/future market prices:
    for pi in portfolio:
        # XXX future prices should also get added
        if isinstance(pi.contract, Stock):
            if pi.marketPrice is not None:
                # XXX check if different values exist?
                addMarketPrice(getName(pi.contract), 1, pi.marketPrice)
                #print('Adding', getName(pi.contract), 'with market price', pi.marketPrice)
    if not UseMarketDataSubscription:
        return
    contracts: list[Contract] = []
    # add all forex pairs:
    USD_QUOTE: set[str] = {'EUR', 'GBP', 'AUD', 'NZD', 'CAD'}
    needed_currencies: list[str] = sorted(list(
        {p.contract.currency for p in portfolio if p.contract.currency != 'USD'}))
    # XXX Add some base currency here to the list, e.g. EURUSD.
    for pair in needed_currencies:
        symbol = f"{pair}USD" if pair in USD_QUOTE else f"USD{pair}"
        contracts.append(Forex(symbol)) # XXX exchange='IDEALPRO'
        #warn_once(logger, f'Fetching forex market price for {symbol}.')
    # add all (future) options to get greeks:
    for pi in portfolio:
        ct = pi.contract
        if isinstance(ct, (Option, FuturesOption)):
            name = getName(ct)
            num = getDataCacheNum(ct)
            if (num, name) not in cache and (num, name) not in greeks_cache:
                cache[(num, name)] = True
                contracts.append(ct)
    # get data from IB:
    if not contracts:
        return
    # XXX Is the limit of 50 messages/second requiring batching into smaller chunks?
    #results: list[Any] = await ib.qualifyContractsAsync(*contracts)
    #tickers: list[Any] = await ib.reqTickersAsync(*results)
    #for i in range(len(contracts)):
    #    contract = results[i]
    #    ticker = tickers[i]
    results = await ib.qualifyContractsAsync(*contracts)
    # Filter out None results and track original indices
    valid: list[Any] = [(c, r) for c, r in zip(contracts, results) if r is not None]
    if not valid:
        return
    tickers = await ib.reqTickersAsync(*[r for _, r in valid])
    for (_, contract), ticker in zip(valid, tickers):
        if contract is None or ticker is None:
            continue
        name = getName(contract)
        if isinstance(contract, (Stock, Future, Forex)):
            marketprice = ticker.marketPrice()
            # XXX Should we also check ticker.midpoint() or ticker.last?
            if marketprice is None or util.isNan(marketprice):
                warn_once(logger, f'Not getting market price for {name}.')
            else:
                #print(name, 'has market price', marketprice)
                num = getDataCacheNum(contract)
                addMarketPrice(name, num, marketprice)
                if isinstance(contract, Forex):
                    pair = name + 'USD'
                    #currency_prices[pair] = marketprice
                    s = format_float(marketprice, pair)
                    logger.warning(f'Adding forex conversion {pair}USD = {s}.')
        elif isinstance(contract, (FuturesOption, Option)):
            gr = ticker.modelGreeks
            if gr is None:
                warn_once(logger, f'Not getting greeks for {name}.')
            else:
                #print(name, 'has delta of', gr.delta)
                num = getDataCacheNum(contract)
                greeks_cache[(num, name)] = gr

# Output different portfolio views:
def showPortfolio(console: Console, accounts: list[str],
    portfolio: list[PortfolioItem], non_options: bool = False, future_options: bool = False,
    options: bool = False, currency_options: bool = False) -> None:
    for account in accounts:
        pf: list[PortfolioItem] = []
        for pi in portfolio:
            if pi.account != account:
                continue
            if non_options and isinstance(pi.contract, (FuturesOption, Option)):
                continue
            if future_options and (not isinstance(pi.contract, FuturesOption)
                or pi.contract.symbol in CURRENCY_SYMBOLS):
                continue
            if options and not isinstance(pi.contract, Option):
                continue
            if currency_options and (not isinstance(pi.contract, FuturesOption)
                or pi.contract.symbol not in CURRENCY_SYMBOLS):
                continue
            pf.append(pi)
        if not pf:
            continue
        # XXX sort pf
        show_options_details = False
        show_prices = False
        if non_options:
            table = Table(title=f'portfolio (without options) {account}')
            show_prices = True
        elif future_options:
            table = Table(title=f'future options portfolio {account}')
            show_options_details = True
        elif options:
            table = Table(title=f'options portfolio {account}')
            show_options_details = True
        elif currency_options:
            table = Table(title=f'currency hedging portfolio {account}')
            show_options_details = True
        else:
            table = Table(title=f'complete portfolio {account}')
        table.add_column('pos.', justify='right')
        table.add_column('instrument')
        table.add_column('PnL', justify='right')
        table.add_column('PnL %', justify='right')
        table.add_column('market value', justify='right')
        table.add_column('cost basis', justify='right')
        if show_prices:
            table.add_column('current price', justify='right')
            table.add_column('average price', justify='right')
        if show_options_details:
            table.add_column('DTE', justify='right')
            table.add_column('daily theta', justify='right')
            table.add_column('price undly', justify='right')
            table.add_column('ITM', justify='right')
            if UseMarketDataSubscription:
                table.add_column('IV', justify='right')
                table.add_column('delta', justify='right')
                table.add_column('delta $', justify='right')
                table.add_column('gamma', justify='right')
                table.add_column('vega', justify='right')
                #table.add_column('theta', justify='right')
                #table.add_column('optPrice', justify='right')
                #table.add_column('undPrice', justify='right')
                #table.add_column('pvDividend', justify='right')
        summe: dict[str, list[float]] = {}
        if show_options_details:
            summe_undl: dict[str, dict[str, list[float]]] = {}
            summe_exp: dict[str, dict[str, list[float]]] = {}
        for pi in pf:
            pnl = pi.unrealizedPNL if pi.unrealizedPNL is not None else 0.0
            curr = get_currency_symbol(pi.contract.currency)
            costbasis = pi.position * pi.averageCost
            pnl_percent = (pnl / abs(costbasis) * 100.0) if costbasis != 0.0 else 0.0
            name = getName(pi.contract)
            row = [f'{getPosition(pi)}', name, f'{pnl:.0f} {curr}', f'{pnl_percent:.0f}%',
                   f'{pi.marketValue:.0f} {curr}', f'{costbasis:.0f} {curr}']
            if show_prices:
                row.extend([f'{pi.marketPrice:.2f} {curr}', f'{pi.averageCost:.2f} {curr}'])
            theta = 0.0
            values = [costbasis, pi.marketValue, theta, 0.0]
            gr: OptionComputation | None = None
            if show_options_details:
                ct = pi.contract
                num = getDataCacheNum(ct)
                gr = getGreeksCache(name, num)
                (theta, dte, undl_price) = getThetaDTE(pi, gr)
                values[2] = theta # XXX ugly
                ITM = 'Yes' if isITM(ct, undl_price) else ''
                undl_price_str = format_float(undl_price, curr)
                row.extend([f'{dte}', f'{theta:.2f} {curr}', undl_price_str, ITM])
                if gr is not None:
                    iv_str = f'{gr.impliedVol * 100.0:.1f} %' if gr.impliedVol is not None else ''
                    (delta, delta_curr, delta_curr_str) = (0.0, 0.0, '')
                    if gr.delta is not None:
                        delta = gr.delta * 100.0
                        if undl_price is not None:
                            delta_curr = gr.delta * undl_price * float(ct.multiplier) * pi.position
                            delta_curr_str = f'{delta_curr:.0f} {curr}'
                        values[3] = delta_curr # XXX ugly
                    gamma_str = f'{gr.gamma:.5f}' if gr.gamma is not None else ''
                    vega_str = f'{gr.vega:.4f}' if gr.vega is not None else ''
                    row.extend([iv_str, f'{delta:.1f}', delta_curr_str, gamma_str,
                                vega_str])
                        #, f'{gr.theta:.5f}'])
                        #f'{gr.optPrice:.2f}', f'{gr.undPrice:.4f}', f'{gr.pvDividend:.4f}'])
                elif UseMarketDataSubscription:
                    row.extend(['', '', '', '', ''])
                if ct.symbol not in summe_undl:
                    summe_undl[ct.symbol] = {}
                accumulate_values(summe_undl[ct.symbol], values, curr)
                exp = ct.lastTradeDateOrContractMonth
                if exp not in summe_exp:
                    summe_exp[exp] = {}
                accumulate_values(summe_exp[exp], values, curr)
            accumulate_values(summe, values, curr)
            table.add_row(*row)
        if show_options_details:
            # add summary lines by expiration date
            table.add_section()
            for exp in sorted(summe_exp.keys()):
                for (curr, values) in summe_exp[exp].items():
                    # XXX should the expiration output be shortened?
                    add_summary(f'total {exp}', values, curr, show_options_details,
                        show_prices, table, '', exp)
            # add summary lines per underlying
            table.add_section()
            for undl in sorted(summe_undl.keys()):
                for (curr, values) in summe_undl[undl].items():
                    undl_price_ = getMarketPrice(undl, 1) # XXX might not be stock
                    undl_price_str = format_float(undl_price_, curr)
                    add_summary(f'total {undl}', values, curr, show_options_details,
                        show_prices, table, undl_price_str, None)
        # summary per invested currency
        table.add_section()
        for (curr, values) in summe.items():
            add_summary(f'total {curr}', values, curr,
                show_options_details, show_prices, table, '', None)
        console.print(Panel(table))

# Output list of options which expire in less than 'dte' days:
def ShowLessThanDTE(accounts: list[str], portfolio: list[PortfolioItem], dte: int) -> None:
    for account in accounts:
        pf: list[PortfolioItem] = []
        for pi in portfolio:
            if pi.account != account or not isinstance(pi.contract, (Option, FuturesOption)):
                continue
            # This might also show already expired options.
            #if getDTE(pi.contract) <= dte:
            if 0 <= getDTE(pi.contract) <= dte:
                pf.append(pi)
        if not pf:
            continue
        print()
        print(f'List all options that expire in {dte} DTE or less for account {account}:')
        for p in pf:
            print(f'{getPosition(p)} {getName(p.contract)} ({getDTE(p.contract)} DTE)')
        print()

# Output list of options which are ITM (In The Money):
def ShowITM(accounts: list[str], portfolio: list[PortfolioItem]) -> None:
    for account in accounts:
        pf: list[tuple[PortfolioItem, float | None]] = []
        for pi in portfolio:
            ct = pi.contract
            if pi.account != account or not isinstance(ct, (Option, FuturesOption)):
                continue
            name = getName(ct)
            num = getDataCacheNum(ct)
            gr = getGreeksCache(name, num)
            if gr is not None and gr.undPrice is not None:
                underlying_price: float | None = gr.undPrice
            else:
                # Stock or Future?
                num = 1 if isinstance(ct, Option) else 4
                underlying_price = getMarketPrice(ct.symbol, num)
            if isITM(ct, underlying_price):
                pf.append((pi, underlying_price))
        if not pf:
            continue
        print()
        print(f'List all In The Money (ITM) options for account {account}:')
        for (p, undl_price) in pf:
            curr = get_currency_symbol(p.contract.currency)
            s = format_float(undl_price, curr)
            print(f'{getPosition(p)} {getName(p.contract)} with underlying price {s}')
        print()

# If all short puts get assigned, what amount of cash (notional value) would be needed
# to pay all these assignments?
# XXX Maybe list all individual short puts with their needed cash sum:
# XXX List notional value of all currency future options and futures.
def ShowNotionalValue(accounts: list[str], portfolio: list[PortfolioItem]) -> None:
    for account in accounts:
        sum_sp: dict[str, list[float]] = {} # sum of all short puts if assigned
        for pi in portfolio:
            ct = pi.contract
            if pi.account != account or not isinstance(ct, Option):
                continue
            # We do not include futures option and also not index option:
            # XXX How can we automate detecting this list? SPXW,RUT,NDX?
            if ct.symbol in ('SPX',):
                continue
            if ct.right != 'P' or pi.position >= 0.0: # not short put
                continue
            curr = get_currency_symbol(ct.currency)
            accumulate_values(sum_sp, (ct.strike * pi.position * float(ct.multiplier),), curr)
        # XXX Also add open trades into notional value calculation.
        if not sum_sp:
            continue
        print()
        for (curr, summe) in sum_sp.items():
            if summe[0] == 0.0:
                continue
            # XXX Show also needed cash as percentage of all available cash:
            #cash_percent = f'{-summe[0] * 100.0 / all_cash:.0f}%' if all_cash > 0.0 else ''
            summe_str = format_float(-summe[0], curr)
            print(f'Cash needed if all short puts get assigned for account {account}: {summe_str}')
        print()

# Debug output for accountValues:
def printAccountValues(accountValues: list[AccountValue]) -> None:
    print()
    print('Account Values:')
    for a in accountValues:
        print(a)

# Summary function to output all portfolio information of the account:
async def showAccounts(ib: IB, console: Console, accounts: list[str] | None = None,
    accountSummary: list[AccountValue] | None = None) -> None:
    if accounts is None:
        accounts = ib.managedAccounts()
    if accountSummary is None:
        accountSummary = await ib.accountSummaryAsync()

    showAccountSummary(console, accounts, accountSummary)

    if verbose >= 3:
        accountValues = ib.accountValues()
        printAccountValues(accountValues)

    # To refresh use: reqAccountUpdatesAsync()
    #portfolio = await ib.portfolioAsync() # XXX
    portfolio = ib.portfolio()
    if not portfolio:
        # XXX allow empty portfolio? Check with paper trading...
        logger.error('Could not read portfolio.')
        return
    if verbose >= 3:
        showPortfolioDebug(portfolio)

    await getPortfolioData(ib, portfolio)
    showPortfolio(console, accounts, portfolio)
    showPortfolio(console, accounts, portfolio, non_options=True)
    showPortfolio(console, accounts, portfolio, future_options=True)
    showPortfolio(console, accounts, portfolio, options=True)
    ShowLessThanDTE(accounts, portfolio, 21)
    ShowLessThanDTE(accounts, portfolio, 6)
    ShowITM(accounts, portfolio)
    ShowNotionalValue(accounts, portfolio)
    showPortfolio(console, accounts, portfolio, currency_options=True)

    # Less information compared to showPortfolio():
    if verbose >= 3:
        positions = ib.positions()
        if positions:
            print()
            print('Positions:')
            for p in positions:
                print(p)

    trades = ib.trades()
    if trades:
        print()
        print('Trades:')
        for t in trades:
            print(t)

    orders = ib.orders()
    if orders:
        print()
        print('Orders:')
        for o in orders:
            print(o)
    #orders = ib.openTrades()
    #print(f'\nOpen Orders: {len(orders)}')
    #for trade in orders:
    #    print(f'{trade.contract.symbol}: {trade.order.action} {trade.order.totalQuantity}')

# argument parser:
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Display IBKR portfolio information',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Use one of the following ports:
- port 7496: TWS active/real/live account
- port 7497: TWS paper account (demo/test)
- port 4001: IB Gateway (IBG) active/real/live account
- port 4002: IB Gateway (IBG) paper account (demo/test)

The client id must be unique per connection/client:
- client_id 0 is getting all transactions, including also TWS.
- client_id 1 (configurable) is getting transactions from other client_ids, but not TWS.

Examples:
  python ib-info.py --host 127.0.0.1 --port 7496 --use-market-data
  python ib-info.py --host 127.0.0.1 --port 7496 --account=U12345
  python ib-info.py --host 127.0.0.1 --port 7496 --short-expire-format
  python ib-info.py --host 127.0.0.1 --port 7496 --debug
        ''')
    # Connection parameters
    parser.add_argument('--host',
        default=os.environ.get('IBKR_HOST', '127.0.0.1'),
        help='TWS/IB-Gateway host (default: %(default)s)')
    parser.add_argument('--port', '-p',
        type=int,
        default=int(os.environ.get('IBKR_PORT', 7496)),
        help='TWS/IB-Gateway port (default: %(default)s)')
    parser.add_argument('--client-id', '-i',
        type=int,
        default=int(os.environ.get('IBKR_CLIENT_ID', 0)),
        help='Client-ID for connection (default: %(default)s)')
    parser.add_argument('--account', '-a',
        default=os.environ.get('IBKR_ACCOUNT', ''),
        help='Limit to specific account (default: all managed accounts)')
    parser.add_argument('--readonly', '-r',
        action='store_true',
        help='Read-only mode (default: False)')
    parser.add_argument('--use-market-data', '-m',
        action='store_true',
        help='Use market data from IBKR (default: False)')
    # Output formatting
    parser.add_argument('--short-expire-format',
        action='store_true',
        dest='short_expire_format',
        help='Do not show current year for expiration dates')
    parser.add_argument('--two-digit-years',
        action='store_true',
        dest='two_digit_years',
        help='Show year output only with 2 digits instead of 4')
    # Verbosity control
    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument('-v', '--verbose',
        action='count',
        default=1,
        help='Increase verbosity (can be repeated: -vv for more verbose)')
    verbosity_group.add_argument('-d', '--debug',
        action='store_true',
        help='Enable debug mode (equivalent to -vvv)')
    verbosity_group.add_argument('-q', '--quiet',
        action='store_true',
        help='Suppress output (opposite of -v)')
    return parser

# Create a network connection to TWS/IBG:
async def safe_connect(host: str, port: int, client_id: int, readonly: bool, account: str) -> IB:
    ib = IB()
    try:
        await ib.connectAsync(host, port, clientId=client_id, readonly=readonly, account=account)
    except ConnectionRefusedError as e:
        logger.error('API connection failed: ConnectionRefusedError: '
                     'Make sure API port on TWS/IBG is open.')
        #sys.exit(1)
        raise SystemExit(1) from e
    except Exception as e:
        logger.exception('Unexpected error connecting to IB:')
        #sys.exit(1)
        raise SystemExit(1) from e
    return ib

async def main(argv: list[str]) -> None:
    global verbose, DoNotShowCurrentYear, ShowYearWithTwoDigits, cur_year
    global UseMarketDataSubscription, delayed_market_data

    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        locale.setlocale(locale.LC_ALL, 'C')
        logger.warning("Failed to set system locale. Falling back to 'C'.")
    #locale.setlocale(locale.LC_ALL, 'de_DE')
    #print(locale.getlocale())
    #for key, value in locale.localeconv().items():
    #    print('%s: %s' % (key, value))

    parser = create_parser()
    args = parser.parse_args(argv)
    ShowYearWithTwoDigits = args.two_digit_years
    DoNotShowCurrentYear = args.short_expire_format
    if DoNotShowCurrentYear:
        today = datetime.date.today()
        cur_year = today.strftime('%Y') # today.year
    if args.debug:
        verbose = 3
    elif args.quiet:
        verbose = 0
    else:
        verbose = args.verbose
    if args.use_market_data:
        UseMarketDataSubscription = True
        delayed_market_data = False

    #config = readConfig('ib-info.ini')

    util.allowCtrlC()

    if verbose == 0:
        util.logToConsole(logging.ERROR)
    elif verbose == 1:
        util.logToConsole(logging.WARNING)
    elif verbose == 2:
        util.logToConsole(logging.INFO)
    elif verbose >= 3:
        util.logToConsole(logging.DEBUG)
    #util.logToFile('ib.log', logging.WARNING)

    ib = None
    ib = await safe_connect(args.host, args.port, args.client_id, args.readonly, args.account)

    #if not ib.isConnected():
    #    logger.error('Not connected: Need to restart TWS/IBG.')
    #    #sys.exit(1)
    #    raise SystemExit(1)

    #await asyncio.sleep(1)

    console = Console()

    # https://interactivebrokers.github.io/tws-api/market_data_type.html
    # 1 == live, realtime with subscriptions
    # 2 == frozen
    # 3 == delayed
    # 4 == delayed frozen
    MarketDataType: int = 4 if delayed_market_data else 1
    ib.reqMarketDataType(MarketDataType)
    #await ib.reqMarketDataTypeAsync(MarketDataType)

    try:
        await showAccounts(ib, console)

    #tasks = []
    #for symbol in symbols:
    #    tasks.append(fetch_data(ib, symbol))
    ##await asyncio.gather(*tasks)

    #ret = await ib.reqContractDetailsAsync(contract)
    #print(ret)

    #option = Option('EOE', '20171215', 490, 'P', 'FTA', multiplier=100)
    #calc = ib.calculateImpliedVolatility(option, optionPrice=6.1, underPrice=525)
    #print(calc)
    #calc = ib.calculateOptionPrice(option, volatility=0.14, underPrice=525)
    #print(calc)

    #spx = Index('SPX', 'CBOE')

    #chains = ib.reqSecDefOptParams(spx.symbol, '', spx.secType, spx.conId)
    #util.df(chains)
    #chain = next(c for c in chains if c.tradingClass == 'SPX' and c.exchange == 'SMART')
    #strikes = [
    #    strike
    #    for strike in chain.strikes
    #    if strike % 5 == 0 and spxValue - 20 < strike < spxValue + 20
    #]
    #expirations = sorted(exp for exp in chain.expirations)[:3]
    #rights = ['P', 'C']
    #contracts = [
    #    Option('SPX', expiration, strike, right, 'SMART', tradingClass='SPX')
    #    for right in rights
    #    for expiration in expirations
    #    for strike in strikes
    #]
    #tickers = ib.reqTickers(*contracts)
    #contracts = ib.qualifyContracts(*contracts)
    #len(contracts)

    #active_tickers = ib.tickers()
    #if active_tickers:
    #logger.info(f"Cancel {len(active_tickers)} subscripions:")
    #for ticker in active_tickers:
    #    logger.info(f"Cancel subscription for {ticker.contract.symbol}.")
    #    try:
    #        ib.cancelMktData(ticker.contract)
    #    except:
    #        pass

    # ticker.askGreeks ticker.bidGreeks ticker.lastGreeks ticker.modelGreeks

    finally:
        if ib is not None:
            ib.disconnect()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
