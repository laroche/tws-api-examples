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
# - Translate all prices into Euro as an option.
# - Fix summary currency on overview pages.
# - Allow translation of output into different languages.
# - For currency overview futures are not yet considered.
# - Add to options output:
#   - price underlying
#   - delta, gamma, theta, vega values
#   - list notional value of all stock option short puts if assigned
#     Show also needed cash as percentage of all available cash.
#   - list all ITM options
#   - list all options < 21 DTE, maybe only if delta is above a certain value
#   - list all long optins with DTE < 60(?) that should get rolled (hedges)
#   - list all short options with delta > 40 that should get rolled
#     - calculate the best delta for rolling options by looking at current prices
#   - grouping of complex (future) options
# - summary per contract type and underlying
# - overview pages markets
# - allow different sorting strategies for overview pages
# - Should large numbers use "." as thousand separator?
# - Output time of last data update from TWS into overview pages.
# - Add cash-like symbols to amount of optional cash: SGOV/BIL, US-T-Bills, TLT...
# - Change to asyncio usage for whole script.
# - Add automatic trading.
# - python: why is getopt a deprecated modul?
#
# pylint: disable=W0511,R0912,C0103,C0114,C0116
#

import sys
import locale
import logging
import datetime
#import asyncio
import ib_async
from ib_async.contract import FuturesOption, Option

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Output configuration:
# Limit year of expiration date to 2 digits only:
ShowYearWithTwoDigits = False
# Do not show current year for expiration dates:
DoNotShowCurrentYear = False

# Futures and Futures-Options that are used for currency hedging
# and should be displayed within an extra overview page:
currency_symbols = ('EUR', 'M6E')

# How verbose should logging be?
verbose = 1

# Turn off some of the more annoying logging output from ib_async
#logging.getLogger('ib_async.ib').setLevel(logging.ERROR)
#logging.getLogger('ib_async.wrapper').setLevel(logging.CRITICAL)

# XXX How to detect base currency?
#BASE = '€'

def get_currency_symbol(curr):
    if curr == 'EUR':
        return '€'
    if curr == 'USD':
        return '$'
    return curr

def print_data(value):
    #if value >= 980000:
    #    return locale.format_string('%d', round(value / 1000), grouping=True) + 'T'
    return locale.format_string('%d', round(value), grouping=True)

def printAccountSummary(accountSummary):
    print()
    print('Account Summary:')
    if accountSummary is not None:
        for a in accountSummary:
            print(a)

def getAccountDetails(accounts, accountSummary):
    ret = []
    for account in accounts:
        nav = 0.0
        nav_str = ''
        cash = 0.0
        cash_str = ''
        cash_percent = ''
        margin = ''
        for p in accountSummary:
            if p.account != account:
                continue
            if p.tag == 'TotalCashValue':
                cash = float(p.value)
                cash_str = print_data(cash) + get_currency_symbol(p.currency)
            elif p.tag == 'Cushion':
                margin = (1.0 - float(p.value)) * 100.0
                margin = f'{margin:.1f}%'
            elif p.tag == 'NetLiquidation':
                nav = float(p.value)
                nav_str = print_data(nav) + get_currency_symbol(p.currency)
        if nav > 0.0:
            cash_percent = str(round(cash * 100 / nav)) + '%'
        ret.append((account, nav_str, margin, cash_str, cash_percent))
    return ret

def showAccountSummary(console, accounts, accountSummary):
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
    for (account, nav, margin, cash, cash_percent) in getAccountDetails(accounts, accountSummary):
        # XXX add info on time of last update
        if account == 'All':
            table.add_section()
        table.add_row(f'{account}', f'{nav}', f'{margin}', f'{cash} ({cash_percent})')
        #table.add_column('US-T: 120 T€ (7%)')
        #table.add_column('Sold Options: -100(12000) (0,05%)')
        #table.add_column('Stocks: 400 T€ (20%)')
    console.print(Panel(table))

def getStrike(contract):
    strike = f'{contract.strike}'
    if strike[-2:] == '.0':
        strike = strike[:-2]
    return strike

cur_year = None

def getPosition(pi):
    pos = f'{pi.position}'
    if pos[-2:] == '.0':
        pos = pos[:-2]
    return pos

def getName(pi):
    global cur_year
    ct = pi.contract
    name = ct.localSymbol
    expiration = ct.lastTradeDateOrContractMonth
    if ShowYearWithTwoDigits:
        expiration = expiration[2:]
    elif DoNotShowCurrentYear:
        if cur_year is None:
            today = datetime.date.today()
            cur_year = today.strftime("%Y") # today.year
        if cur_year == expiration[:4]:
            expiration = expiration[4:]
    if isinstance(ct, (FuturesOption, Option)):
        name = f'{ct.symbol} {ct.right}{getStrike(ct)} {expiration}'
    return name

def getDTE(contract):
    expiration = contract.lastTradeDateOrContractMonth
    if len(expiration) != 8:
        # XXX Does this happen? Should we then find the date of
        # the monthly expiration as extra search?
        #dte = datetime.datetime.strptime(expiration, "%Y%m")
        raise ValueError(f'Expiration date ({expiration}) has not length of 8.')
    dte = datetime.datetime.strptime(expiration, "%Y%m%d")
    dte = dte.date() - datetime.date.today()
    return dte.days

def showPortfolioDebug(portfolio):
    print()
    print('Portfolio:')
    for p in portfolio:
        print(p)

def showPortfolio(console, accounts, portfolio, non_options=False,
    future_options=False, options=False, currency_options=False):
    for account in accounts:
        pf = []
        for pi in portfolio:
            if pi.account != account:
                continue
            if non_options and isinstance(pi.contract, (FuturesOption, Option)):
                continue
            if future_options and (not isinstance(pi.contract, FuturesOption)
                or pi.contract.symbol in currency_symbols):
                continue
            if options and not isinstance(pi.contract, Option):
                continue
            if currency_options and (not isinstance(pi.contract, FuturesOption)
                or pi.contract.symbol not in currency_symbols):
                continue
            pf.append((pi, pi.position, getName(pi), pi.unrealizedPNL, pi.marketValue,
                pi.marketPrice, pi.averageCost, pi.contract.currency))
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
        sum_kostenbasis = 0.0
        sum_d = 0.0
        for (pi, pos, name, pnl, market_value, price, average_price, curr) in pf:
            curr = get_currency_symbol(curr)
            kostenbasis = pos * average_price
            sum_kostenbasis += kostenbasis
            sum_d += market_value
            guv_prozent = 0.0
            if kostenbasis != 0.0:
                guv_prozent = (pnl / abs(kostenbasis)) * 100.0
            if show_options_details:
                table.add_row(f'{getPosition(pi)}', str(name), f'{pnl:.0f} {curr}',
                    f'{guv_prozent:.0f}%', f'{market_value:.0f} {curr}',
                    f'{kostenbasis:.0f} {curr}',
                    str(price), str(average_price), f'{getDTE(pi.contract):.0f}')
            else:
                table.add_row(f'{getPosition(pi)}', str(name), f'{pnl:.0f} {curr}',
                    f'{guv_prozent:.0f}%', f'{market_value:.0f} {curr}',
                    f'{kostenbasis:.0f} {curr}',
                    str(price), str(average_price))
        table.add_section()
        pnl = sum_d - sum_kostenbasis
        guv_prozent = 0.0
        if sum_kostenbasis != 0.0:
            guv_prozent = (pnl / abs(sum_kostenbasis)) * 100.0
        curr = 'X'  # XXX Do we mix differnet currencies here?
        if show_options_details:
            table.add_row('', '', f'{pnl:.0f} {curr}', f'{guv_prozent:.1f}%',
                f'{sum_d:.0f} {curr}', f'{sum_kostenbasis:.0f} {curr}', '', '', '')
        else:
            table.add_row('', '', f'{pnl:.0f} {curr}', f'{guv_prozent:.1f}%',
                f'{sum_d:.0f} {curr}', f'{sum_kostenbasis:.0f} {curr}', '', '')
        console.print(Panel(table))

def printAccountValues(accountValues):
    print()
    print('Account Values:')
    for a in accountValues:
        print(a)

def ShowLessThan21DTE(accounts, portfolio):
    for account in accounts:
        pf = []
        for pi in portfolio:
            if pi.account != account or not isinstance(pi.contract, Option):
                continue
            if getDTE(pi.contract) <= 21:
                pf.append(pi)
        if not pf:
            continue
        print()
        print(f'List all options that expire in 21 DTE or less for account {account}:')
        for p in pf:
            print(f'{getPosition(p)} {getName(p)} ({getDTE(p.contract)} DTE)')
        print()

def ShowITM(accounts, portfolio):
    for account in accounts:
        pf = []
        for pi in portfolio:
            ct = pi.contract
            if pi.account != account or not isinstance(ct, Option):
                continue
            # XXX pi.marketPrice should be market price of the underlying
            if ct.right == 'P' and pi.marketPrice < ct.strike:
                pf.append(pi)
            if ct.right == 'C' and pi.marketPrice > ct.strike:
                pf.append(pi)
        if not pf:
            continue
        print()
        print(f'List all In The Money (ITM) options for account {account}:')
        for p in pf:
            print(f'{getPosition(p)} {getName(p)} with price {p.marketPrice:.0f}')
        print()

# XXX Maybe list all individual short puts with their needed cash sum:
def ShowNotionalValue(accounts, portfolio):
    for account in accounts:
        curr = 'X' # XXX currency
        sum_sp = 0.0
        for pi in portfolio:
            ct = pi.contract
            if pi.account != account or not isinstance(ct, Option):
                continue
            if ct.right == 'P' and pi.position < 0.0:
                sum_sp -= ct.strike * pi.position * float(ct.multiplier)
        if sum_sp == 0.0:
            continue
        # XXX Show also needed cash as percentage of all available cash:
        #cash_percent = str(round(sum_sp * 100.0 / all_cash)) + '%'
        print()
        print(f'Cash needed if all short puts get assigned for account {account}: {sum_sp:.0f} {curr}')
        print()

def showAccounts(ib, console, accounts=None, accountSummary=None):
    if accounts is None:
        accounts = ib.managedAccounts()
    if accountSummary is None:
        accountSummary = ib.accountSummary()

    showAccountSummary(console, accounts, accountSummary)

    if verbose >= 3:
        accountValues = ib.accountValues()
        printAccountValues(accountValues)

    portfolio = ib.portfolio()
    if not portfolio:
        print('ERROR: Could not read portfolio.')
        return
    if verbose >= 3:
        showPortfolioDebug(portfolio)

    showPortfolio(console, accounts, portfolio)
    showPortfolio(console, accounts, portfolio, non_options=True)
    showPortfolio(console, accounts, portfolio, future_options=True)
    showPortfolio(console, accounts, portfolio, options=True)
    ShowLessThan21DTE(accounts, portfolio)
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

def usage():
    print('ib-info.py ' +
        '[--host=127.0.0.1][--port=7496][--client-id=0][--readonly][--acount=U12345]' +
        '[--short-expire-format]' +
        '[--help][--verbose][--debug][--quiet]')

def main(argv):
    global verbose, DoNotShowCurrentYear
    import getopt

    locale.setlocale(locale.LC_ALL, '')
    #locale.setlocale(locale.LC_ALL, 'de_DE')
    #print(locale.getlocale())
    #for key, value in locale.localeconv().items():
    #    print('%s: %s' % (key, value))
    #logger = logging.getLogger(__name__)

    # Connect params to your Interactive Brokers (IB) TWS or IB Gateway:
    host = '127.0.0.1'
    #port = 7497 # TWS paper account (demo/test)
    port = 7496  # TWS active/real/live account
    #port = 4002 # IB Gateway (IBG) paper account (demo/test)
    #port = 4001 # IB Gateway (IBG) active/real/live account
    client_id = 0
    # client_id must be unique per connection
    # client_id 0 is getting all transactions, including also TWS.
    # client_id 1 (configurable) is getting transactions from other client_ids, but not TWS.
    # Only read access?
    readonly = False
    # Limit to a specific account:
    account = ''

    try:
        opts, args = getopt.getopt(argv, 'adhipqrv', ['help',
            'host=', 'port=', 'client-id=', 'readonly', 'account=',
            'short-expire-format',
            'quiet', 'verbose', 'debug'])
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            usage()
            sys.exit()
        elif opt == '--host':
            host = arg
        elif opt in ('-p', '--port'):
            port = int(arg)
        elif opt in ('-i', '--client-id'):
            client_id = int(arg)
        elif opt  in ('-r', '--readonly'):
            readonly = True
        elif opt in ('-a', '--account'):
            account = arg
        elif opt == '--short-expire-format':
            DoNotShowCurrentYear = True
        elif opt in ('-v', '--verbose'):
            verbose += 1
        elif opt in ('-d', '--debug'):
            verbose = 3
        elif opt in ('-q', '--quiet'):
            verbose = 0
    #if len(args) == 0:
    #    usage()
    #    sys.exit()

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

    ib = ib_async.IB()
    try:
        ib.connect(host, port, clientId=client_id, readonly=readonly, account=account)
    except ConnectionRefusedError:
        print('ERROR API connection failed: ConnectionRefusedError: '
              'Make sure API port on TWS/IBG is open.')
        sys.exit(1)

    console = Console()

    showAccounts(ib, console)

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
    main(sys.argv[1:])
