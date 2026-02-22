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

import sys
import locale
import logging
#import asyncio
import ib_async

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Turn off some of the more annoying logging output from ib_async
#logging.getLogger("ib_async.ib").setLevel(logging.ERROR)
#logging.getLogger("ib_async.wrapper").setLevel(logging.CRITICAL)

# XXX How to detect base currency?
BASE = '€'

def print_data(value):
    #if value >= 980000:
    #    return locale.format_string("%d", round(value / 1000), grouping=True) + 'T'
    return locale.format_string("%d", round(value), grouping=True)

def show_account2(ib):
    #accountValues = ib.accountValues()
    #printAccountValues(accountValues):
    portfolio = ib.portfolio() # account=
    if portfolio:
        print('Portfolio:')
        for p in portfolio:
            print(p)
    positions = ib.positions()
    if positions:
        print('Positions:')
        for p in positions:
            print(p)
    trades = ib.trades()
    if trades:
        print('Trades:')
        for t in trades:
            print(t)
    orders = ib.orders()
    if orders:
        print('Orders:')
        for o in orders:
            print(o)
    #orders = ib.openTrades()
    #print(f"\nOpen Orders: {len(orders)}")
    #for trade in orders:
    #    print(f"{trade.contract.symbol}: {trade.order.action} {trade.order.totalQuantity}")

def get_currency_symbol(curr):
    if curr == 'EUR':
        return '€'
    if curr == 'USD':
        return '$'
    return curr

def getAccountDetails(accounts, accountSummary=None):
    ret = []
    if accountSummary is None:
        accountSummary = ib.accountSummary()
    for a in accounts:
        nav = .0
        nav_str = ''
        cash = .0
        cash_str = ''
        cash_percent = ''
        margin = ''
        for p in accountSummary:
            if p.account != a:
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
        if nav > .0:
            cash_percent = str(round(cash * 100 / nav)) + '%'
        ret.append((a, nav_str, margin, cash_str, cash_percent))
    return ret

def printAccountSummary(accountSummary):
    print('Account Summary:')
    for a in accountSummary:
        print(a)

def printAccountValues(accountValues):
    print('Account Values:')
    for a in accountValues:
        print(a)

def show_accounts(ib, console, verbose):
    accounts = ib.managedAccounts()
    accountSummary = ib.accountSummary()
    #printAccountSummary(accountSummary)
    for (account, nav, margin, cash, cash_percent) in getAccountDetails(accounts, accountSummary):
        if len(accounts) > 1:
            table = Table(title="Accounts: %s" % (",".join(accounts)))
        else:
            table = Table(title="Account: %s" % (",".join(accounts)))
        # XXX add info on time of last update
        table.add_column(f"Account: {account}")
        table.add_column(f"NetLiq: {nav}")
        table.add_column(f"Margin: {margin}")
        table.add_column(f"Cash: {cash} ({cash_percent})")
        #table.add_column("US-T: 120 T€ (7%)")
        #table.add_column("Sold Options: -100(12000) (0,05%)")
        #table.add_column("Stocks: 400 T€ (20%)")
    console.print(Panel(table))

    show_account2(ib)

def usage():
    print('ib-info.py ' +
        '[--host=127.0.0.1][--port=7496][--client-id=0]' +
        '[--help][--verbose][--debug][--quiet]')

def main(argv):
    import getopt

    locale.setlocale(locale.LC_ALL, '')
    #locale.setlocale(locale.LC_ALL, 'de_DE')
    #print(locale.getlocale())
    #for key, value in locale.localeconv().items():
    #    print("%s: %s" % (key, value))
    #logger = logging.getLogger(__name__)

    verbose = 1

    # Connect params to your Interactive Brokers (IB) TWS or IB Gateway:
    host = '127.0.0.1'
    #port = 7497 # TWS paper account (demo/test)
    port = 7496  # TWS active/real/live account
    #port = 4002 # IB Gateway (IBG) paper account (demo/test)
    #port = 4001 # IB Gateway (IBG) active/real/live account
    client_id = 0
    # client_id 0 is getting all transactions, including also TWS.
    # client_id 1 (configurable) is getting transactions from other client_ids, but not TWS.

    try:
        opts, args = getopt.getopt(argv, 'dhqv', ['list-index', 'help',
            'host=', 'port=', 'client-id='
            'data-dir=', 'quiet', 'verbose', 'debug'])
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            usage()
            sys.exit()
        elif opt == '--host':
            host = arg
        elif opt == '--port':
            port = int(arg)
        elif opt == '--client-id':
            client_id = int(arg)
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
    #ib_async.util.logToFile("ib.log", logging.WARNING)

    ib = ib_async.IB()
    try:
        ib.connect(host, port, clientId=client_id) # account=, timeout=
    except ConnectionRefusedError:
        sys.exit(1)

    console = Console()

    if False:
        table = Table(title="Account summary")
        table.add_column("Item")
        table.add_column("Value", justify="right")
        table.add_row("Net liquidation", "0")
        table.add_row("Maintenance margin", "0")
        table.add_row("Total cash", "0")
        table.add_section()
        table.add_row("Total cash", "0")
        console.print(Panel(table))


    show_accounts(ib, console, verbose)

    # ib.reqMarketDataType(self.config["account"]["market_data_type"])
    # 3 == delayed
    # 4 == delayed frozen
    # 1 == realtime with subscriptions

    #option = Option('EOE', '20171215', 490, 'P', 'FTA', multiplier=100)
    #calc = ib.calculateImpliedVolatility(option, optionPrice=6.1, underPrice=525)
    #print(calc)
    #calc = ib.calculateOptionPrice(option, volatility=0.14, underPrice=525)
    #print(calc)

    #spx = Index("SPX", "CBOE")
    #ib.qualifyContracts(spx)
    #ib.reqMarketDataType(4)
    #[ticker] = ib.reqTickers(spx)
    #spxValue = ticker.marketPrice()
    #chains = ib.reqSecDefOptParams(spx.symbol, "", spx.secType, spx.conId)
    #util.df(chains)
    #chain = next(c for c in chains if c.tradingClass == "SPX" and c.exchange == "SMART")
    #strikes = [
    #    strike
    #    for strike in chain.strikes
    #    if strike % 5 == 0 and spxValue - 20 < strike < spxValue + 20
    #]
    #expirations = sorted(exp for exp in chain.expirations)[:3]
    #rights = ["P", "C"]
    #contracts = [
    #    Option("SPX", expiration, strike, right, "SMART", tradingClass="SPX")
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
