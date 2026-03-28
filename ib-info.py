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
#
# TODO:
# - Make this also a web application.
# - Translate all prices into Euro (base currency) as an option.
# - Allow translation of output into different languages.
# - For currency overview futures are not yet included.
# - Allow for nice/modern config file.
# - Add to options output:
#   - delta, gamma, theta, vega values
#   - list notional value of all stock option short puts if assigned
#     Show also needed cash as percentage of all available cash.
#   - list all options < 21 DTE, maybe only if delta is above a certain value
#   - list all long options with DTE < 60(?) that should get rolled (hedges, Delta < 5)
#   - list all short options with delta > 40 that should get rolled
#     - calculate the best delta/time for rolling options by looking at current prices
#   - list all short call options not covered by stock
#   - list weighted average strike price for Put/Call Short Options per underlying
#   - grouping of complex (future) options, advise on next steps for strategies
#   - getDTE() output should get cached
# - summary per contract type and underlying
# - Assets per currency overview: list all $/EUR-denominated assets.
# - overview pages markets
# - Warn if margin is above certain level. No new (option) positions above a certain level.
#   Close contracts above a certain level?
# - allow different sorting strategies for overview pages
# - Should large numbers use "." as thousand separator?
# - Output time of last data update from TWS into overview pages.
# - Add cash-like symbols to amount of optional cash: SGOV/BIL, US-T-Bills, TLT...
# - Warn about negative cash values.
# - Add automatic trading and advise on trading strategies.
# - If TWS is suspended (due to mobile app started), this script times out and hangs.
# - How to allow for re-connects?
# - Should disconnect be done within a finally clause in case of errors?
# - add sqlite database for historical data?
#
# pylint: disable=W0511,R0912,C0103,C0114,C0115,C0116
#

#from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from functools import lru_cache
from enum import Enum
import sys
import os
import locale
import logging
import datetime
import argparse
import asyncio
from ib_async import (IB, FuturesOption, Option, AccountValue, PortfolioItem, Contract,
    Stock, Ticker, Index, Forex, util)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# How verbose should logging be?
verbose: int = 1

# Output configuration:
# Limit year of expiration date to 2 digits only:
ShowYearWithTwoDigits: bool = False
# Do not show current year for expiration dates:
DoNotShowCurrentYear: bool = False

# Futures and Futures-Options that are used for currency hedging
# and should be displayed within an extra overview page:
CURRENCY_SYMBOLS = {'EUR', 'M6E'}

logger = logging.getLogger(__name__)

# Keep track of 30 different messages and then warn again
@lru_cache(30)
def warn_once(mylogger: logging.Logger, msg: str) -> None:
    mylogger.warning(msg)

# Turn off some of the more annoying logging output from ib_async
#import ib_async
#logging.getLogger('ib_async.ib').setLevel(logging.ERROR)
#logging.getLogger('ib_async.wrapper').setLevel(logging.CRITICAL)

UseMarketDataSubscription: bool = False

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
#            import datetime
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

async def qualify_contracts(ib: IB, *contracts: Contract) -> list[Contract]:
    results = await ib.qualifyContractsAsync(*contracts)
    qualified: list[Contract] = []
    for r in results:
        if r is None:
            continue
        if isinstance(r, list):
            qualified.extend([c for c in r if c is not None])
        else:
            qualified.append(r)
    return qualified

async def __market_data_streaming_handler__(ib: IB, contract: Contract, generic_tick_list: str,
    handler: Callable[[Ticker], Awaitable[Any]]) -> Ticker:
    """
    Handles the streaming of market data for a given contract.

    This asynchronous method qualifies the contract, requests market data,
    and processes the data using the provided handler. Once the handler
    completes, the market data request is canceled.

    Args:
        contract (Contract): The contract for which market data is requested.
        handler (Callable[[Ticker], Awaitable[None]]): An asynchronous function
            that processes the received market data ticker.

    Returns:
        Ticker: The market data ticker for the given contract.
    """
    if not contract.conId:
        qualified = await qualify_contracts(ib, contract)
        if qualified:
            contract = qualified[0]
    if not contract.conId:
        raise ValueError(f"Contract {contract} can't be qualified because no 'conId' value exists.")
    ticker = ib.reqMktData(contract, genericTickList=generic_tick_list)
    await handler(ticker)
    return ticker

api_response_wait_time: int = 60
#default_order_exchange: str = 'SMART'
default_order_exchange: str = 'AMEX'

async def __ticker_wait_for_condition__(ticker: Ticker, condition: Callable[[Ticker], bool],
                                        timeout: float) -> bool:
    event = asyncio.Event()

    def onTicker(ticker: Ticker) -> None:
        if condition(ticker):
            event.set()

    ticker.updateEvent += onTicker
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        ticker.updateEvent -= onTicker

async def __wait_for_midpoint_price__(ticker: Ticker) -> bool:
    return await __ticker_wait_for_condition__(ticker, lambda t: not util.isNan(t.midpoint()),
        api_response_wait_time)

async def __wait_for_market_price__(ticker: Ticker) -> bool:
    return await __ticker_wait_for_condition__(ticker, lambda t: not util.isNan(t.marketPrice()),
        api_response_wait_time)

async def __wait_for_greeks__(ticker: Ticker) -> bool:
    return await __ticker_wait_for_condition__(ticker,
        lambda t: not (t.modelGreeks is None or t.modelGreeks.delta is None or
        util.isNan(t.modelGreeks.delta)), api_response_wait_time)

async def __wait_for_open_interest__(ticker: Ticker) -> bool:
    def open_interest_is_not_ready(ticker: Ticker) -> bool:
        if not ticker.contract:
            return False
        if ticker.contract.right.startswith('P'):
            return util.isNan(ticker.putOpenInterest)
        else:
            return util.isNan(ticker.callOpenInterest)

    return await __ticker_wait_for_condition__(ticker, lambda t: not open_interest_is_not_ready(t),
        api_response_wait_time)

class RequiredFieldValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)

class TickerField(Enum):
    MIDPOINT = 'midpoint'
    MARKET_PRICE = 'market_price'
    GREEKS = 'greeks'
    OPEN_INTEREST = 'open_interest'

def __ticker_field_handler__(ticker_field: TickerField) -> Callable[[Ticker], Awaitable[bool]]:
    if ticker_field == TickerField.MIDPOINT:
        return __wait_for_midpoint_price__
    if ticker_field == TickerField.MARKET_PRICE:
        return __wait_for_market_price__
    if ticker_field == TickerField.GREEKS:
        return __wait_for_greeks__
    if ticker_field == TickerField.OPEN_INTEREST:
        return __wait_for_open_interest__

async def get_ticker_for_contract(ib: IB, contract: Contract, generic_tick_list: str = '',
    required_fields: list[TickerField] = [TickerField.MARKET_PRICE],
    optional_fields: list[TickerField] = [TickerField.MIDPOINT]) -> Ticker:
    required_handlers = [
        (field, __ticker_field_handler__(field)) for field in required_fields
    ]
    optional_handlers = [
        (field, __ticker_field_handler__(field)) for field in optional_fields
    ]

    async def ticker_handler(ticker: Ticker) -> None:
        required_tasks = [handler(ticker) for _, handler in required_handlers]
        optional_tasks = [handler(ticker) for _, handler in optional_handlers]

        # Gather results, allowing optional tasks to potentially fail (timeout)
        results = await asyncio.gather(
            asyncio.gather(*required_tasks),
            asyncio.gather(
                *optional_tasks, return_exceptions=False
            ),  # Don't raise exceptions here for optional
        )
        required_results = results[0]
        optional_results = results[1]

        # Check required results
        failed_required_fields = [
            field.name
            for i, (field, _) in enumerate(required_handlers)
            if not required_results[i]
        ]
        if failed_required_fields:
            raise RequiredFieldValidationError(
                f"Required fields timed out for {contract.localSymbol}: {', '.join(failed_required_fields)}"
            )

        # Log warnings for optional results that timed out
        failed_optional_fields = [
            field.name
            for i, (field, _) in enumerate(optional_handlers)
            if not optional_results[i]
        ]
        if failed_optional_fields:
            logger.warning(
                f"Optional fields timed out for {contract.localSymbol}: {', '.join(failed_optional_fields)}"
            )

    return await __market_data_streaming_handler__(ib, contract, generic_tick_list,
        lambda ticker: ticker_handler(ticker))

async def get_ticker_for_stock(ib: IB, symbol: str, primary_exchange: str,
    order_exchange: str | None = None, generic_tick_list: str = '',
    required_fields: list[TickerField] = [TickerField.MARKET_PRICE],
    optional_fields: list[TickerField] = [TickerField.MIDPOINT]) -> Ticker:
    stock = Stock(symbol, order_exchange or default_order_exchange,
        currency='USD', primaryExchange=primary_exchange)
    qualified = await qualify_contracts(ib, stock)
    contract: Contract = qualified[0] if qualified else stock

    if not contract.conId:
        # Some underlyings (e.g. SPX) are indices, not stocks.
        index_exchange = primary_exchange or 'CBOE'
        index_contract = Index(symbol, index_exchange, 'USD')
        qualified_index = await qualify_contracts(ib, index_contract)
        if qualified_index:
            contract = qualified_index[0]

    return await get_ticker_for_contract(ib, contract, generic_tick_list,
        required_fields, optional_fields)

currency_prices: dict[str, float] = {}

async def getTickData(ib: IB, contract: Contract) -> float | None:
    qualified = await qualify_contracts(ib, contract)
    if not qualified:
        # XXX check contract.symbol if correct error output:
        warn_once(logger, f'Not getting market price for {contract.symbol}.')
        return None
    contract = qualified[0]
    ib.reqMktData(contract, '', False, False)
    ticker = ib.ticker(contract)
    if ticker is None:
        warn_once(logger, f'Not getting market price for {contract.symbol}.')
        return None
    ret = await __wait_for_market_price__(ticker)
    if ret is False:
        warn_once(logger, f'Not getting market price for {contract.symbol}.')
        return None
    return ticker.marketPrice()

async def setupForex(ib: IB) -> None:
    # XXX Find out needed_currencies by inspecting the portfolio.
    needed_currencies = ['EUR']
    # XXX Query for all contracts in parallel:
    #contracts = [ Forex(pair) for pair in needed_currencies ]
    for pair in needed_currencies:
        forex_ = Forex(pair + 'USD')
        qualified = await qualify_contracts(ib, forex_)
        if not qualified:
            warn_once(logger,
                f'Not getting market price for {pair}USD.')
            continue
        forex = qualified[0]
        #print(forex)
        #ret = await ib.reqContractDetailsAsync(forex)
        #print(ret)
        ib.reqMktData(forex, '', False, False)
        ticker = ib.ticker(forex)
        if ticker is None:
            warn_once(logger,
                f'Not getting market price for {pair}USD.')
            continue
        ret = await __wait_for_market_price__(ticker)
        if ret is False:
            warn_once(logger,
                f'Not getting market price for {pair}USD.')
            continue
        marketPrice = ticker.marketPrice()
        currency_prices[pair] = marketPrice
        #logger.info(f'Adding forex conversion {pair}USD = {marketPrice:.4f}.')
        logger.warning(f'Adding forex conversion {pair}USD = {marketPrice:.4f}.')

# Convert currency name into short currency symbol:
currency_conversion = {
    'EUR': '€',
    'USD': '$'}

def get_currency_symbol(curr: str) -> str:
    return currency_conversion.get(curr, curr)

def print_data(value: float) -> str:
    #if value >= 980000:
    #    return locale.format_string('%d', round(value / 1000), grouping=True) + 'T'
    return locale.format_string('%d', round(value), grouping=True)

# Debugging output of accountSummary:
def printAccountSummary(accountSummary: list[AccountValue]) -> None:
    print()
    print('Account Summary:')
    for a in accountSummary:
        print(a)

# Extract key data from accountSummary:
def getAccountDetails(accounts: list[str], accountSummary: list[AccountValue]) -> list[tuple[str,
    str, str, str, str]]:
    ret = []
    for account in accounts:
        (nav, nav_str, cash, cash_str, margin) = (0.0, '', 0.0, '', '')
        for p in accountSummary:
            if p.account != account:
                continue
            if p.tag == 'TotalCashValue':
                cash = float(p.value)
                cash_str = print_data(cash) + get_currency_symbol(p.currency)
            elif p.tag == 'Cushion':
                m = (1.0 - float(p.value)) * 100.0
                margin = f'{m:.1f}%'
            elif p.tag == 'NetLiquidation':
                nav = float(p.value)
                nav_str = print_data(nav) + get_currency_symbol(p.currency)
        cash_percent = str(round(cash * 100.0 / nav)) + '%' if nav > 0.0 else ''
        ret.append((account, nav_str, margin, cash_str, cash_percent))
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
    for (account, nav, margin, cash, cash_percent) in getAccountDetails(accounts, accountSummary):
        # XXX add info on time of last update
        if account == 'All':
            table.add_section()
        table.add_row(f'{account}', f'{nav}', f'{margin}', f'{cash} ({cash_percent})')
    console.print(Panel(table))

# Store market price of instruments into a dictionary:
MarketPrices: dict[str, float] = {}

def collectStockMarketPrices(portfolio: list[PortfolioItem]) -> None:
    for pi in portfolio:
        # XXX future prices should also get added
        if isinstance(pi.contract, Stock):
            # XXX check if different values exist?
            MarketPrices[pi.contract.localSymbol] = pi.marketPrice

async def getStockMarketPrice(symbol: str, contract: Contract | None, ib: IB) -> float | None:
    MarketPrice = MarketPrices.get(symbol)
    if MarketPrice is not None:
        return MarketPrice
    if not UseMarketDataSubscription:
        warn_once(logger,
            f'Not getting market price for {symbol}. ITM/theta calculations might be wrong.')
        return None
    # Now ask for current online market price:
    # XXX: if not isinstance(contract, Stock): #XXX isinstance(contract, FuturesOption):
    if isinstance(contract, FuturesOption) or contract is None: # XXX symbol == 'EUR':
        warn_once(logger,
            f'Not getting market price for {symbol}. ITM/theta calculations might be wrong.')
        return None
    # XXX support SMART or other/better defaults:
    contract = Stock(symbol, 'AMEX', currency='USD', primaryExchange='AMEX')
    #contract = Stock(symbol, 'SMART', currency='USD', primaryExchange='AMEX')
    MarketPrice = await getTickData(ib, contract)
    if MarketPrice is None:
        warn_once(logger,
            f'Not getting market price for {symbol}. ITM/theta calculations might be wrong.')
    else:
        MarketPrices[symbol] = MarketPrice
    return MarketPrice
    #ticker = await get_ticker_for_stock(ib, symbol, primaryExchange)
    #ticker = await get_ticker_for_stock(ib, symbol, 'AMEX', 'AMEX') # XXX
    # XXX add symbol, ticker.marketPrice() into dict MarketPrices
    #return ticker.marketPrice()

# Strip ".0" at end of string:
def strip_decimal_zero(value: str) -> str:
    return value[:-2] if value.endswith('.0') else value

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

# Return DTE (Days Til Expiration) for an option/future:
#@lru_cache(maxsize=1024)
def getDTE(contract: Contract) -> int:
    expiration = contract.lastTradeDateOrContractMonth
    if len(expiration) != 8:
        # XXX Does this happen? Should we then find the date of
        # the monthly expiration as extra search?
        #dte = datetime.datetime.strptime(expiration, '%Y%m')
        logger.error('Wrong expiration date: %s (length != 8).', expiration)
        raise ValueError(f'Expiration date ({expiration}) has not length of 8.')
    d = datetime.datetime.strptime(expiration, '%Y%m%d')
    dte = d.date() - datetime.date.today()
    return dte.days

# Return daily theta, DTE and underlying_price:
async def getThetaDTE(pi: PortfolioItem, ib: IB) -> tuple[float, int, float | None]:
    ct = pi.contract
    dte = getDTE(ct)
    value = pi.marketValue # this is intrinsic + extrinsic value
    underlying_price = await getStockMarketPrice(ct.symbol, ct, ib)
    if underlying_price is not None:
        # subtract intrinsic value
        if ct.right == 'P' and underlying_price < ct.strike:
            value -= (ct.strike - underlying_price) * float(ct.multiplier) * pi.position
        if ct.right == 'C' and underlying_price > ct.strike:
            value -= (underlying_price - ct.strike) * float(ct.multiplier) * pi.position
    theta = value / (dte + 1) if dte >= 0 else 0.0
    return (theta, dte, underlying_price)

# Debug output of portfolio data:
def showPortfolioDebug(portfolio: list[PortfolioItem]) -> None:
    print()
    print('Portfolio:')
    for p in portfolio:
        print(p)

# Sum up values within individual portfolio items:
def accumulate_values(d: dict[str, list[float]], values: list[float], currency: str) -> None:
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
    show_prices: bool, table: Table, underlying_price: str) -> None:
    (sum_costbasis, sum_marketValue, sum_theta) = values
    pnl = sum_marketValue - sum_costbasis
    pnl_percent = (pnl / abs(sum_costbasis)) * 100.0 if sum_costbasis != 0.0 else 0.0
    row = ['', name, f'{pnl:.0f} {curr}', f'{pnl_percent:.1f}%',
           f'{sum_marketValue:.0f} {curr}', f'{sum_costbasis:.0f} {curr}']
    if show_prices:
        row.extend(['', ''])
    if show_options_details:
        row.extend(['', f'{sum_theta:.2f} {curr}', underlying_price, ''])
    table.add_row(*row)

# Output different portfolio views:
async def showPortfolio(ib: IB, console: Console, accounts: list[str],
    portfolio: list[PortfolioItem], non_options: bool = False, future_options: bool = False,
    options: bool = False, currency_options: bool = False) -> None:
    for account in accounts:
        pf = []
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
            table.add_column('price underlying', justify='right')
            table.add_column('ITM', justify='right')
        summe: dict[str, list[float]] = {}
        if show_options_details:
            summe_undl: dict[str, dict[str, list[float]]] = {}
            summe_exp: dict[str, dict[str, list[float]]] = {}
        for pi in pf:
            pnl = pi.unrealizedPNL
            curr = get_currency_symbol(pi.contract.currency)
            costbasis = pi.position * pi.averageCost
            pnl_percent = (pnl / abs(costbasis) * 100.0) if costbasis != 0.0 else 0.0
            name = getName(pi.contract)
            row = [f'{getPosition(pi)}', name, f'{pnl:.0f} {curr}', f'{pnl_percent:.0f}%',
                   f'{pi.marketValue:.0f} {curr}', f'{costbasis:.0f} {curr}']
            if show_prices:
                row.extend([f'{pi.marketPrice:.2f} {curr}', f'{pi.averageCost:.2f} {curr}'])
            theta = 0.0
            if show_options_details:
                ct = pi.contract
                (theta, dte, undl_price) = await getThetaDTE(pi, ib)
                undl_price_ = f'{undl_price:.2f} {curr}' if undl_price is not None else ''
                ITM = 'Yes' if isITM(ct, undl_price) else ''
                row.extend([f'{dte:.0f}', f'{theta:.2f} {curr}', undl_price_, ITM])
                if ct.symbol not in summe_undl:
                    summe_undl[ct.symbol] = {}
                accumulate_values(summe_undl[ct.symbol], [costbasis, pi.marketValue, theta], curr)
                exp = ct.lastTradeDateOrContractMonth
                if exp not in summe_exp:
                    summe_exp[exp] = {}
                accumulate_values(summe_exp[exp], [costbasis, pi.marketValue, theta], curr)
            accumulate_values(summe, [costbasis, pi.marketValue, theta], curr)
            table.add_row(*row)
        table.add_section()
        for (curr, values) in summe.items():
            add_summary(f'total {curr}', values, curr,
                show_options_details, show_prices, table, '')
        if show_options_details:
            table.add_section()
            # add summary lines per underlying
            for undl in sorted(summe_undl.keys()):
                for (curr, values) in summe_undl[undl].items():
                    undl_price = await getStockMarketPrice(undl, None, ib)
                    undl_price_ = f'{undl_price:.2f} {curr}' if undl_price is not None else ''
                    add_summary(f'total {undl}', values, curr, show_options_details,
                        show_prices, table, undl_price_)
            table.add_section()
            # add summary lines by expiration date
            for exp in sorted(summe_exp.keys()):
                for (curr, values) in summe_exp[exp].items():
                    # XXX should the expiration output be shortened?
                    add_summary(f'total {exp}', values, curr, show_options_details,
                        show_prices, table, '')
        console.print(Panel(table))

# Debug output for accountValues:
def printAccountValues(accountValues: list[AccountValue]) -> None:
    print()
    print('Account Values:')
    for a in accountValues:
        print(a)

# Output list of options which expire in less than 'dte' days:
def ShowLessThanDTE(accounts: list[str], portfolio: list[PortfolioItem], dte: int) -> None:
    for account in accounts:
        pf = []
        for pi in portfolio:
            if pi.account != account or not isinstance(pi.contract, Option):
                continue
            if getDTE(pi.contract) <= dte:
                pf.append(pi)
        if not pf:
            continue
        print()
        print(f'List all options that expire in {dte} DTE or less for account {account}:')
        for p in pf:
            print(f'{getPosition(p)} {getName(p.contract)} ({getDTE(p.contract)} DTE)')
        print()

# Output list of options which are ITM (In The Money):
async def ShowITM(ib: IB, accounts: list[str], portfolio: list[PortfolioItem]) -> None:
    for account in accounts:
        pf = []
        for pi in portfolio:
            ct = pi.contract
            # XXX Also output ITM Future Options?
            if pi.account != account or not isinstance(ct, Option):
                continue
            underlying_price = await getStockMarketPrice(ct.symbol, ct, ib)
            if isITM(ct, underlying_price):
                pf.append((pi, underlying_price))
        if not pf:
            continue
        print()
        print(f'List all In The Money (ITM) options for account {account}:')
        for (p, undl_price) in pf:
            curr = get_currency_symbol(p.contract.currency)
            print(f'{getPosition(p)} {getName(p.contract)} with price {undl_price:.2f} {curr}')
        print()

# If all short puts get assigned, what amount of cash (notional vlaue) would be needed
# to pay all these assignments?
# XXX Maybe list all individual short puts with their needed cash sum:
def ShowNotionalValue(accounts: list[str], portfolio: list[PortfolioItem]) -> None:
    for account in accounts:
        sum_sp: dict[str, list[float]] = {} # sum of all short puts if assigned
        for pi in portfolio:
            ct = pi.contract
            if pi.account != account or not isinstance(ct, Option):
                continue
            if ct.right != 'P' or pi.position >= 0.0: # not short put
                continue
            curr = get_currency_symbol(ct.currency)
            accumulate_values(sum_sp, [ct.strike * pi.position * float(ct.multiplier)], curr)
        # XXX Also add open trades into notional value calculation.
        if not sum_sp:
            continue
        print()
        for (curr, summe) in sum_sp.items():
            if summe[0] == 0.0:
                continue
            # XXX Show also needed cash as percentage of all available cash:
            #cash_percent = str(round(-summe[0] * 100.0 / all_cash)) + '%'
            summe_str = print_data(-summe[0]) + curr
            print(f'Cash needed if all short puts get assigned for account {account}: {summe_str}')
        print()

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
    portfolio = ib.portfolio()
    if not portfolio:
        # XXX allow empty portfolio? Check with paper trading...
        logger.error('Could not read portfolio.')
        return
    if verbose >= 3:
        showPortfolioDebug(portfolio)

    collectStockMarketPrices(portfolio)
    # XXX await setupForex(ib)
    await showPortfolio(ib, console, accounts, portfolio)
    await showPortfolio(ib, console, accounts, portfolio, non_options=True)
    await showPortfolio(ib, console, accounts, portfolio, future_options=True)
    await showPortfolio(ib, console, accounts, portfolio, options=True)
    ShowLessThanDTE(accounts, portfolio, 21)
    ShowLessThanDTE(accounts, portfolio, 4)
    await ShowITM(ib, accounts, portfolio)
    ShowNotionalValue(accounts, portfolio)
    await showPortfolio(ib, console, accounts, portfolio, currency_options=True)

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
  python ib-info.py --host 127.0.0.1 --port 7496 --short-expire-format
  python ib-info.py --host 127.0.0.1 --port 7496 --account=U12345
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

    locale.setlocale(locale.LC_ALL, '')
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

    ib = await safe_connect(args.host, args.port, args.client_id, args.readonly, args.account)

    #if not ib.isConnected():
    #    logger.error('Not connected: Need to restart TWS/IBG.')
    #    #sys.exit(1)
    #    raise SystemExit(1)

    #await asyncio.sleep(1)

    console = Console()

    # 1 == realtime with subscriptions
    # 3 == delayed
    # 4 == delayed frozen
    ib.reqMarketDataType(4)

    await showAccounts(ib, console)

    #tasks = []
    #for symbol in symbols:
    #    tasks.append(fetch_data(ib, symbol))
    ##await asyncio.gather(*tasks)

    #option = Option('EOE', '20171215', 490, 'P', 'FTA', multiplier=100)
    #calc = ib.calculateImpliedVolatility(option, optionPrice=6.1, underPrice=525)
    #print(calc)
    #calc = ib.calculateOptionPrice(option, volatility=0.14, underPrice=525)
    #print(calc)

    #ib.reqMarketDataType(4)
    #spx = Stock('IBIT', 'SMART', currency='USD')
    #spx = Stock('IBIT', 'AMEX', currency='USD')
    #spx = Stock('IBIT', 'AMEX', currency='USD', primaryExchange='AMEX')
    #await ib.qualifyContractsAsync(spx)
    #ib.reqMktData(spx, "", False, False)
    #ticker = ib.ticker(spx)
    #print(ticker)
    #await asyncio.sleep(2)
    #print(ticker)
    #print(ticker.marketPrice())

    #ib.reqMarketDataType(4)
    #spx = Index('SPX', 'CBOE')
    #await ib.qualifyContractsAsync(spx)
    #ib.reqMktData(spx, "", False, False)
    #ticker = ib.ticker(spx)
    #print(ticker)
    #await asyncio.sleep(2)
    #print(ticker)
    #print(ticker.marketPrice())

    #[ticker] = await ib.reqTickersAsync(spx)
    #spxValue = ticker.marketPrice()
    #await asyncio.sleep(2)
    #print(spxValue)
    #print(ticker.marketPrice())

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

    # ticker.askGreeks ticker.bidGreeks ticker.lastGreeks ticker.modelGreeks

    ib.disconnect()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
