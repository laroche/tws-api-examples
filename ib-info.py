#!/usr/bin/env python3
#
# Copyright (C) 2023,2026 Florian La Roche <Florian.LaRoche@gmail.com>
#
# Tested on Debian. (Should run fine on Ubuntu.)
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
# TODO:
# - Make this also a web application.
# - Translate all prices into Euro as an option.
# - Allow translation of output into different languages.
# - For currency overview futures are not yet included.
# - Add to options output:
#   - price underlying
#   - delta, gamma, theta, vega values
#   - list notional value of all stock option short puts if assigned
#     Show also needed cash as percentage of all available cash.
#   - list all ITM options
#   - list all options < 21 DTE, maybe only if delta is above a certain value
#   - list all long optins with DTE < 60(?) that should get rolled (hedges, Delta < 5)
#   - list all short options with delta > 40 that should get rolled
#     - calculate the best delta for rolling options by looking at current prices
#   - list all short call options not covered by stock
#   - grouping of complex (future) options
#   - getDTE() output should get cached
# - summary per contract type and underlying
# - overview pages markets
# - allow different sorting strategies for overview pages
# - Should large numbers use "." as thousand separator?
# - Output time of last data update from TWS into overview pages.
# - Add cash-like symbols to amount of optional cash: SGOV/BIL, US-T-Bills, TLT...
# - Add automatic trading.
# - If TWS is suspended, this script times out without any real timeout.
# - How to allow for re-connects?
#
# pylint: disable=W0511,R0912,C0103,C0114,C0115,C0116
#

#from dataclasses import dataclass
from typing import cast
import sys
import os
import locale
import logging
import datetime
import argparse
import asyncio
import ib_async
from ib_async import IB, FuturesOption, Option, AccountValue, PortfolioItem, Contract

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

# Turn off some of the more annoying logging output from ib_async
#logging.getLogger('ib_async.ib').setLevel(logging.ERROR)
#logging.getLogger('ib_async.wrapper').setLevel(logging.CRITICAL)

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
#            cfg.current_year = datetime.date.today().strftime("%Y")
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
    # Filter out None values and flatten any nested lists
    qualified: list[Contract] = []
    for result in results:
        if result is None:
            pass
        elif isinstance(result, list):
            for contract in result:
                if contract is not None:
                    qualified.append(cast(Contract, contract))
        else:
            qualified.append(result)
    return qualified

currency_conversion = {
    'EUR': '€',
    'USD': '$'}

def get_currency_symbol(curr: str) -> str:
    return currency_conversion.get(curr, curr)

def print_data(value: float) -> str:
    #if value >= 980000:
    #    return locale.format_string('%d', round(value / 1000), grouping=True) + 'T'
    return locale.format_string('%d', round(value), grouping=True)

def printAccountSummary(accountSummary: list[AccountValue]) -> None:
    print()
    print('Account Summary:')
    for a in accountSummary:
        print(a)

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
        cash_percent = ''
        if nav > 0.0:
            cash_percent = str(round(cash * 100.0 / nav)) + '%'
        ret.append((account, nav_str, margin, cash_str, cash_percent))
    return ret

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

def strip_decimal_zero(value: str) -> str:
    return value[:-2] if value.endswith('.0') else value

def getPosition(pi: PortfolioItem) -> str:
    return strip_decimal_zero(f'{pi.position}')

def getStrike(contract: Contract) -> str:
    return strip_decimal_zero(f'{contract.strike}')

# Current year:
cur_year: str | None = None

def getName(contract: Contract) -> str:
    if not isinstance(contract, (FuturesOption, Option)):
        return contract.localSymbol
    expiration = contract.lastTradeDateOrContractMonth
    if ShowYearWithTwoDigits:
        expiration = expiration[2:]
    elif DoNotShowCurrentYear:
        if cur_year == expiration[:4]:
            expiration = expiration[4:]
    return f'{contract.symbol} {contract.right}{getStrike(contract)} {expiration}'

#from functools import lru_cache
#@lru_cache(maxsize=1024)
def getDTE(contract: Contract) -> int:
    expiration = contract.lastTradeDateOrContractMonth
    if len(expiration) != 8:
        # XXX Does this happen? Should we then find the date of
        # the monthly expiration as extra search?
        #dte = datetime.datetime.strptime(expiration, "%Y%m")
        logger.error('Wrong expiration date: %s (length != 8).', expiration)
        raise ValueError(f'Expiration date ({expiration}) has not length of 8.')
    d = datetime.datetime.strptime(expiration, "%Y%m%d")
    dte = d.date() - datetime.date.today()
    return dte.days

def showPortfolioDebug(portfolio: list[PortfolioItem]) -> None:
    print()
    print('Portfolio:')
    for p in portfolio:
        print(p)

def accumulate_values(d: dict[str, list[float]], values: list[float], currency: str) -> None:
    """Generic accumulator for currency-keyed dictionaries."""
    # Check if we need to add a new currency:
    if d.get(currency) is None:
        d[currency] = [0.0] * len(values)
    # Add to all entries for this currency:
    for i, v in enumerate(values):
        d[currency][i] += v

def showPortfolio(console: Console, accounts: list[str], portfolio: list[PortfolioItem],
    non_options: bool = False, future_options: bool = False, options: bool = False,
    currency_options: bool = False) -> None:
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
        if non_options:
            table = Table(title=f'Portfolio (ohne Optionen) von {account}')
        elif future_options:
            table = Table(title=f'Future-Optionen-Portfolio von {account}')
            show_options_details = True
        elif options:
            table = Table(title=f'Options-Portfolio von {account}')
            show_options_details = True
        elif currency_options:
            table = Table(title=f'Währungs-Portfolio von {account}')
            show_options_details = True
        else:
            table = Table(title=f'Portfolio von {account}')
        table.add_column('Anzahl', justify='right')
        table.add_column('Name')
        table.add_column('GuV', justify='right')
        table.add_column('GuV %', justify='right')
        table.add_column('Marktwert', justify='right')
        table.add_column('Kostenbasis', justify='right')
        table.add_column('aktueller Kurs', justify='right')
        table.add_column('Durchschnittskurs', justify='right')
        if show_options_details:
            table.add_column('DTE', justify='right')
            #table.add_column('Kurs vom Basiswert', justify='right')
        summe: dict[str, list[float]] = {}
        for pi in pf:
            pnl = pi.unrealizedPNL
            curr = get_currency_symbol(pi.contract.currency)
            kostenbasis = pi.position * pi.averageCost
            accumulate_values(summe, [kostenbasis, pi.marketValue], curr)
            guv_prozent = (pnl / abs(kostenbasis) * 100.0) if kostenbasis != 0.0 else 0.0
            name = getName(pi.contract)
            row = [f'{getPosition(pi)}', name, f'{pnl:.0f} {curr}', f'{guv_prozent:.0f}%',
                   f'{pi.marketValue:.0f} {curr}', f'{kostenbasis:.0f} {curr}',
                   f'{pi.marketPrice}', f'{pi.averageCost}']
            if show_options_details:
                row.append(f'{getDTE(pi.contract):.0f}')
            table.add_row(*row)
        table.add_section()
        for (curr, values) in summe.items():
            (sum_kostenbasis, sum_marketValue) = values
            pnl = sum_marketValue - sum_kostenbasis
            guv_prozent = 0.0
            if sum_kostenbasis != 0.0:
                guv_prozent = (pnl / abs(sum_kostenbasis)) * 100.0
            row = ['', '', f'{pnl:.0f} {curr}', f'{guv_prozent:.1f}%',
                   f'{sum_marketValue:.0f} {curr}', f'{sum_kostenbasis:.0f} {curr}', '', '']
            if show_options_details:
                row.append('')
            table.add_row(*row)
        console.print(Panel(table))

def printAccountValues(accountValues: list[AccountValue]) -> None:
    print()
    print('Account Values:')
    for a in accountValues:
        print(a)

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

def ShowITM(accounts: list[str], portfolio: list[PortfolioItem]) -> None:
    for account in accounts:
        pf = []
        for pi in portfolio:
            ct = pi.contract
            if pi.account != account or not isinstance(ct, Option):
                continue
            # XXX
            #ticker = await ibkr.get_ticker_for_stock(ct.symbol, ct.primaryExchange)
            #marketPrice = ticker.marketPrice()
            marketPrice = 0.0
            if ct.right == 'P' and marketPrice <= ct.strike:
                pf.append(pi)
            if ct.right == 'C' and marketPrice >= ct.strike:
                pf.append(pi)
        if not pf:
            continue
        print()
        print(f'List all In The Money (ITM) options for account {account}:')
        for p in pf:
            print(f'{getPosition(p)} {getName(p.contract)} with price {p.marketPrice:.0f}')
        print()

# XXX Maybe list all individual short puts with their needed cash sum:
def ShowNotionalValue(accounts: list[str], portfolio: list[PortfolioItem]) -> None:
    for account in accounts:
        sum_sp: dict[str, list[float]] = {}
        for pi in portfolio:
            ct = pi.contract
            if pi.account != account or not isinstance(ct, Option):
                continue
            if ct.right == 'P' and pi.position < 0.0:
                curr = get_currency_symbol(ct.currency)
                accumulate_values(sum_sp, [ct.strike * pi.position * float(ct.multiplier)], curr)
        if not sum_sp:
            continue
        print()
        for (curr, summe) in sum_sp.items():
            if summe[0] == 0.0:
                continue
            # XXX Show also needed cash as percentage of all available cash:
            #cash_percent = str(round(sum_sp * 100.0 / all_cash)) + '%'
            print(f'Cash needed if all short puts get assigned for account {account}: {-summe[0]:.0f} {curr}')
        print()

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

    portfolio = ib.portfolio()
    if not portfolio:
        # XXX allow empty portfolio?
        logger.error('Could not read portfolio.')
        return
    if verbose >= 3:
        showPortfolioDebug(portfolio)

    showPortfolio(console, accounts, portfolio)
    showPortfolio(console, accounts, portfolio, non_options=True)
    showPortfolio(console, accounts, portfolio, future_options=True)
    showPortfolio(console, accounts, portfolio, options=True)
    ShowLessThanDTE(accounts, portfolio, 21)
    ShowLessThanDTE(accounts, portfolio, 2)
    #ShowITM(accounts, portfolio)
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

def usage() -> None:
    print('ib-info.py ' +
        '[--host=127.0.0.1][--port=7496][--client-id=0][--readonly][--acount=U12345]' +
        '[--short-expire-format]' +
        '[--help][--verbose][--debug][--quiet]')

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Display IBKR portfolio information',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python ib-info.py --host 127.0.0.1 --port 7496 -v
  python ib-info.py --account U12345 --readonly
  python ib-info.py --debug --short-expire-format
        ''')
    # Connection parameters
    parser.add_argument('--host',
        default=os.environ.get('IBKR_HOST', '127.0.0.1'),
        help='TWS/IB-Gateway host (default: %(default)s)')
    parser.add_argument('-p', '--port',
        type=int,
        default=int(os.environ.get('IBKR_PORT', 7496)),
        help='TWS/IB-Gateway port (default: %(default)s)')
    #port 7497: TWS paper account (demo/test)
    #port 7496: TWS active/real/live account
    #port 4002: IB Gateway (IBG) paper account (demo/test)
    #port 4001: IB Gateway (IBG) active/real/live account
    parser.add_argument('-i', '--client-id',
        type=int,
        default=int(os.environ.get('IBKR_CLIENT_ID', 0)),
        help='Client-ID for connection (default: %(default)s)')
    # client_id must be unique per connection
    # client_id 0 is getting all transactions, including also TWS.
    # client_id 1 (configurable) is getting transactions from other client_ids, but not TWS.
    parser.add_argument('-a', '--account',
        default=os.environ.get('IBKR_ACCOUNT', ''),
        help='Limit to specific account (default: all managed accounts)')
    parser.add_argument('-r', '--readonly',
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
        cur_year = today.strftime("%Y") # today.year
    if args.debug:
        verbose = 3
    elif args.quiet:
        verbose = 0
    else:
        verbose = args.verbose

    #config = readConfig('ib-info.ini')

    ib_async.util.allowCtrlC()

    if verbose == 0:
        ib_async.util.logToConsole(logging.ERROR)
    elif verbose == 1:
        ib_async.util.logToConsole(logging.WARNING)
    elif verbose == 2:
        ib_async.util.logToConsole(logging.INFO)
    elif verbose >= 3:
        ib_async.util.logToConsole(logging.DEBUG)
    #ib_async.util.logToFile('ib.log', logging.WARNING)

    ib = await safe_connect(args.host, args.port, args.client_id, args.readonly, args.account)

    #if ib.isConnected():
    #await asyncio.sleep(1)

    console = Console()

    await showAccounts(ib, console)

    #tasks = []
    #for symbol in symbols:
    #    tasks.append(fetch_data(ib, symbol))
    ##await asyncio.gather(*tasks)

    # ib.reqMarketDataType(self.config['account']['market_data_type'])
    # 3 == delayed
    # 4 == delayed frozen
    # 1 == realtime with subscriptions

    #option = Option('EOE', '20171215', 490, 'P', 'FTA', multiplier=100)
    #calc = ib.calculateImpliedVolatility(option, optionPrice=6.1, underPrice=525)
    #print(calc)
    #calc = ib.calculateOptionPrice(option, volatility=0.14, underPrice=525)
    #print(calc)

    #spx = Index('SPX', 'CBOE')
    #ib.qualifyContracts(spx)
    #ib.reqMarketDataType(4)
    #[ticker] = ib.reqTickers(spx)
    #spxValue = ticker.marketPrice()
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

    ib.disconnect()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
