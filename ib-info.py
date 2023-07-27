#!/usr/bin/env python3
#
# Copyright (C) 2023 Florian La Roche <Florian.LaRoche@gmail.com>
#
# Tested on Debian-11 and Debian-12 (Should run fine on Ubuntu.):
# sudo apt-get install python3-rich python3-pandas
# python3 -m venv venv
# . venv/bin/activate
# pip3 install ib_insync
#

import sys
import locale
import logging
import ib_insync

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Turn off some of the more annoying logging output from ib_insync
#logging.getLogger("ib_insync.ib").setLevel(logging.ERROR)
#logging.getLogger("ib_insync.wrapper").setLevel(logging.CRITICAL)

# XXX How to detect base currency?
BASE = '€'

def print_data(value):
    if value >= 980000:
        return locale.format_string("%d", round(value / 1000), grouping=True) + 'T'
    return locale.format_string("%d", round(value), grouping=True)

def show_account2(ib):
    #print([v for v in ib.accountValues()
    #       if v.tag == 'NetLiquidationByCurrency' and v.currency == 'BASE'])
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

def show_account(ib, console, verbose):
    accounts = ib.managedAccounts()
    accountValues = ib.accountValues()
    if verbose >= 3 and accountValues:
        print('Account Values:')
        for p in accountValues:
            print(p)
    accountSummary = ib.accountSummary()
    if verbose >= 3 and accountSummary:
        print('Account Summary:')
        for p in accountSummary:
            print(p)
    nav = .0
    nav_str = ''
    cash = .0
    cash_str = ''
    cash_percent = ''
    margin = ''
    for p in accountSummary:
        if p.account == 'All' and p.tag == 'TotalCashBalance' and p.currency == 'BASE':
            cash = float(p.value)
            cash_str = print_data(cash) + BASE
        if p.tag == 'Cushion':
            margin = str(100 - round(float(p.value) * 100)) + '%'
        if p.tag == 'NetLiquidation':
            nav = float(p.value)
            nav_str = print_data(nav) + BASE
    if nav > .0:
        cash_percent = str(round(cash * 100 / nav)) + '%'
    if len(accounts) > 1:
        table = Table(title="Accounts: %s" % (",".join(accounts)))
    else:
        table = Table(title="Account: %s" % (",".join(accounts)))
    # XXX add info on time of last update
    if len(accounts) > 1:
        table.add_column("Accounts: %s" % (",".join(accounts)))
    else:
        table.add_column("Account: %s" % (",".join(accounts)))
    table.add_column(f"NetLiq: {nav_str}")
    table.add_column(f"Margin: {margin}")
    table.add_column(f"Cash: {cash_str} ({cash_percent})")
    #table.add_column("US-T: 120 T€ (7%)")
    #table.add_column("Sold Options: -100(12000) (0,05%)")
    #table.add_column("Stocks: 400 T€ (20%)")
    console.print(Panel(table))

    if verbose >= 3:
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
    port = 7496 # TWS active/real/live account
    #port = 4002 # IB Gateway paper account (demo/test)
    #port = 4001 # IB Gateway active/real/live account
    client_id = 0

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

    ib_insync.util.allowCtrlC()

    if verbose == 0:
        ib_insync.util.logToConsole(logging.ERROR)
    elif verbose == 1:
        ib_insync.util.logToConsole(logging.WARNING)
    elif verbose == 2:
        ib_insync.util.logToConsole(logging.INFO)
    elif verbose >= 3:
        ib_insync.util.logToConsole(logging.DEBUG)
    #ib_insync.util.logToFile("ib.log", logging.WARNING)

    ib = ib_insync.IB()
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


    show_account(ib, console, verbose)

    # ib.reqMarketDataType(self.config["account"]["market_data_type"])

    ib.disconnect()

if __name__ == '__main__':
    main(sys.argv[1:])
