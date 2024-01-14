#! /usr/bin/python3
#
# Download Interactive Brokers (IB) historical stock market data
# by connecting to the local TWS software.
# Data is stored per default into the directory "data".
#
# Required (tested on Debian 11 and 12):
# sudo apt-get install python3-pandas
# pip3 install ib_insync
#
# Old requirement:
# sudo apt-get install python3-sqlalchemy-utils
#
# TODO:
# - Also support parquet fileformat in addition to csv: pd.read_parquet() pd.to_parquet().
# - Cache also empty data returns?
# - Note date of data download and date of last check
# - Add account id into sql filename?
# - Check m_primaryExch as official exchange, also see m_validExchanges.
# - Use also ARCA as exchange?
# - List of exchanges? GLOBEX, CMECRYPTO, ECBOT, NYMEX
# - Check: https://interactivebrokers.github.io/tws-api/contract_details.html
# - Check time delta handling: hourly data for 2023 contains some hours from 2022.
# - Does hourly data make sense? Often half hour data is part of RTH. ???
# - Configuration: allow env config settings for TWS connection and separate config file.
# - Robust constantly running prog with re-connects to TWS to allow automatic trading.
#
# pylint: disable=C0103,C0114,C0116,C0413,C0415,W0603,W0614
#

import sys
import os
import time
import logging

import pandas
import ib_insync


# https://en.wikipedia.org/wiki/List_of_S%26P_500_companies
# also check: https://github.com/deltaray-io/US-Stock-Symbols
SP500: tuple[str, ...] = (
    'A', 'AAL', 'AAPL', 'ABBV', 'ABNB', 'ABT', 'ACGL', 'ACN', 'ADBE', 'ADI',
    'ADM', 'ADP', 'ADSK', 'AEE', 'AEP', 'AES', 'AFL', 'AIG', 'AIZ', 'AJG',
    'AKAM', 'ALB', 'ALGN', 'ALL', 'ALLE', 'AMAT', 'AMCR', 'AMD', 'AME', 'AMGN',
    'AMP', 'AMT', 'AMZN', 'ANET', 'ANSS', 'AON', 'AOS', 'APA', 'APD', 'APH',
    'APTV', 'ARE', 'ATO', 'AVB', 'AVGO', 'AVY', 'AWK', 'AXON', 'AXP', 'AZO',
    'BA', 'BAC', 'BALL', 'BAX', 'BBWI', 'BBY', 'BDX', 'BEN', 'BF.B', 'BG',
    'BIIB', 'BIO', 'BK', 'BKNG', 'BKR', 'BLDR', 'BLK', 'BMY', 'BR', 'BRK.B',
    'BRO', 'BSX', 'BWA', 'BX', 'BXP', 'C', 'CAG', 'CAH', 'CARR', 'CAT', 'CB',
    'CBOE', 'CBRE', 'CCI', 'CCL', 'CDAY', 'CDNS', 'CDW', 'CE', 'CEG', 'CF',
    'CFG', 'CHD', 'CHRW', 'CHTR', 'CI', 'CINF', 'CL', 'CLX', 'CMA', 'CMCSA',
    'CME', 'CMG', 'CMI', 'CMS', 'CNC', 'CNP', 'COF', 'COO', 'COP', 'COR',
    'COST', 'CPB', 'CPRT', 'CPT', 'CRL', 'CRM', 'CSCO', 'CSGP', 'CSX', 'CTAS',
    'CTLT', 'CTRA', 'CTSH', 'CTVA', 'CVS', 'CVX', 'CZR', 'D', 'DAL', 'DD',
    'DE', 'DFS', 'DG', 'DGX', 'DHI', 'DHR', 'DIS', 'DLR', 'DLTR', 'DOV', 'DOW',
    'DPZ', 'DRI', 'DTE', 'DUK', 'DVA', 'DVN', 'DXCM', 'EA', 'EBAY', 'ECL',
    'ED', 'EFX', 'EG', 'EIX', 'EL', 'ELV', 'EMN', 'EMR', 'ENPH', 'EOG', 'EPAM',
    'EQIX', 'EQR', 'EQT', 'ES', 'ESS', 'ETN', 'ETR', 'ETSY', 'EVRG', 'EW',
    'EXC', 'EXPD', 'EXPE', 'EXR', 'F', 'FANG', 'FAST', 'FCX', 'FDS', 'FDX',
    'FE', 'FFIV', 'FI', 'FICO', 'FIS', 'FITB', 'FLT', 'FMC', 'FOX', 'FOXA',
    'FRT', 'FSLR', 'FTNT', 'FTV', 'GD', 'GE', 'GEHC', 'GEN', 'GILD', 'GIS',
    'GL', 'GLW', 'GM', 'GNRC', 'GOOG', 'GOOGL', 'GPC', 'GPN', 'GRMN', 'GS',
    'GWW', 'HAL', 'HAS', 'HBAN', 'HCA', 'HD', 'HES', 'HIG', 'HII', 'HLT',
    'HOLX', 'HON', 'HPE', 'HPQ', 'HRL', 'HSIC', 'HST', 'HSY', 'HUBB', 'HUM',
    'HWM', 'IBM', 'ICE', 'IDXX', 'IEX', 'IFF', 'ILMN', 'INCY', 'INTC', 'INTU',
    'INVH', 'IP', 'IPG', 'IQV', 'IR', 'IRM', 'ISRG', 'IT', 'ITW', 'IVZ', 'J',
    'JBHT', 'JBL', 'JCI', 'JKHY', 'JNJ', 'JNPR', 'JPM', 'K', 'KDP', 'KEY',
    'KEYS', 'KHC', 'KIM', 'KLAC', 'KMB', 'KMI', 'KMX', 'KO', 'KR', 'KVUE', 'L',
    'LDOS', 'LEN', 'LH', 'LHX', 'LIN', 'LKQ', 'LLY', 'LMT', 'LNT', 'LOW',
    'LRCX', 'LULU', 'LUV', 'LVS', 'LW', 'LYB', 'LYV', 'MA', 'MAA', 'MAR',
    'MAS', 'MCD', 'MCHP', 'MCK', 'MCO', 'MDLZ', 'MDT', 'MET', 'META', 'MGM',
    'MHK', 'MKC', 'MKTX', 'MLM', 'MMC', 'MMM', 'MNST', 'MO', 'MOH', 'MOS',
    'MPC', 'MPWR', 'MRK', 'MRNA', 'MRO', 'MS', 'MSCI', 'MSFT', 'MSI', 'MTB',
    'MTCH', 'MTD', 'MU', 'NCLH', 'NDAQ', 'NDSN', 'NEE', 'NEM', 'NFLX', 'NI',
    'NKE', 'NOC', 'NOW', 'NRG', 'NSC', 'NTAP', 'NTRS', 'NUE', 'NVDA', 'NVR',
    'NWS', 'NWSA', 'NXPI', 'O', 'ODFL', 'OKE', 'OMC', 'ON', 'ORCL', 'ORLY',
    'OTIS', 'OXY', 'PANW', 'PARA', 'PAYC', 'PAYX', 'PCAR', 'PCG', 'PEAK',
    'PEG', 'PEP', 'PFE', 'PFG', 'PG', 'PGR', 'PH', 'PHM', 'PKG', 'PLD', 'PM',
    'PNC', 'PNR', 'PNW', 'PODD', 'POOL', 'PPG', 'PPL', 'PRU', 'PSA', 'PSX',
    'PTC', 'PWR', 'PXD', 'PYPL', 'QCOM', 'QRVO', 'RCL', 'REG', 'REGN', 'RF',
    'RHI', 'RJF', 'RL', 'RMD', 'ROK', 'ROL', 'ROP', 'ROST', 'RSG', 'RTX',
    'RVTY', 'SBAC', 'SBUX', 'SCHW', 'SHW', 'SJM', 'SLB', 'SNA', 'SNPS', 'SO',
    'SPG', 'SPGI', 'SRE', 'STE', 'STLD', 'STT', 'STX', 'STZ', 'SWK', 'SWKS',
    'SYF', 'SYK', 'SYY', 'T', 'TAP', 'TDG', 'TDY', 'TECH', 'TEL', 'TER', 'TFC',
    'TFX', 'TGT', 'TJX', 'TMO', 'TMUS', 'TPR', 'TRGP', 'TRMB', 'TROW', 'TRV',
    'TSCO', 'TSLA', 'TSN', 'TT', 'TTWO', 'TXN', 'TXT', 'TYL', 'UAL', 'UBER',
    'UDR', 'UHS', 'ULTA', 'UNH', 'UNP', 'UPS', 'URI', 'USB', 'V', 'VFC',
    'VICI', 'VLO', 'VLTO', 'VMC', 'VRSK', 'VRSN', 'VRTX', 'VTR', 'VTRS', 'VZ',
    'WAB', 'WAT', 'WBA', 'WBD', 'WDC', 'WEC', 'WELL', 'WFC', 'WHR', 'WM',
    'WMB', 'WMT', 'WRB', 'WRK', 'WST', 'WTW', 'WY', 'WYNN', 'XEL', 'XOM',
    'XRAY', 'XYL', 'YUM', 'ZBH', 'ZBRA', 'ZION', 'ZTS')

# old stock symbols who got merged, renamed, removed:
SP500old: tuple[str, ...] = ('FB', 'PVH')

# https://en.wikipedia.org/wiki/NASDAQ-100
NASDAQ100: tuple[str, ...] = (
    'ADBE', 'ADP', 'ABNB', 'GOOGL', 'GOOG', 'AMZN', 'AMD', 'AEP', 'AMGN',
    'ADI', 'ANSS', 'AAPL', 'AMAT', 'ASML', 'AZN', 'TEAM', 'ADSK', 'BKR',
    'BIIB', 'BKNG', 'AVGO', 'CDNS', 'CDW', 'CHTR', 'CTAS', 'CSCO', 'CCEP',
    'CTSH', 'CMCSA', 'CEG', 'CPRT', 'CSGP', 'COST', 'CRWD', 'CSX', 'DDOG',
    'DXCM', 'FANG', 'DLTR', 'DASH', 'EA', 'EXC', 'FAST', 'FTNT', 'GEHC',
    'GILD', 'GFS', 'HON', 'IDXX', 'ILMN', 'INTC', 'INTU', 'ISRG', 'KDP',
    'KLAC', 'KHC', 'LRCX', 'LULU', 'MAR', 'MRVL', 'MELI', 'META', 'MCHP', 'MU',
    'MSFT', 'MRNA', 'MDLZ', 'MDB', 'MNST', 'NFLX', 'NVDA', 'NXPI', 'ORLY',
    'ODFL', 'ON', 'PCAR', 'PANW', 'PAYX', 'PYPL', 'PDD', 'PEP', 'QCOM', 'REGN',
    'ROP', 'ROST', 'SIRI', 'SPLK', 'SBUX', 'SNPS', 'TTWO', 'TMUS', 'TSLA',
    'TXN', 'TTD', 'VRSK', 'VRTX', 'WBA', 'WBD', 'WDAY', 'XEL', 'ZS')

REITS: tuple[str, ...] = ('ARE', 'AMT', 'AVB', 'BXP', 'CPT', 'CBRE', 'CCI',
    'DLR', 'DRE', 'EQUIX', 'EQR', 'ESS', 'EXR', 'FRT', 'PEAK', 'HST', 'INVH',
    'IRM', 'KIM', 'MAA', 'PLD', 'PSA', 'O', 'REG', 'SBAC', 'SPG', 'UDR',
    'VTR', 'VICI', 'VNO', 'WELL', 'WY')

# Read all companies of the SP500 from wikipedia.
def read_sp500() -> pandas.DataFrame:
    table = pandas.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')
    df = table[0]
    #print(df.info())
    #df.drop('SEC filings', axis=1, inplace=True)
    return df

def print_sp500() -> None:
    import pprint
    df = read_sp500()
    #df['Symbol'] = df['Symbol'].str.replace('.', '/')
    symbols = df['Symbol'].values.tolist()
    symbols.sort()
    p = pprint.pformat(symbols, width=79, compact=True, indent=4)
    print(p)
    # XXX print REITS: df['GICS Sector'] == 'Real Estate'

def read_nasdaq100() -> pandas.DataFrame:
    table = pandas.read_html('https://en.wikipedia.org/wiki/NASDAQ-100')
    df = table[4]
    return df

def print_nasdaq100() -> None:
    import pprint
    df = read_nasdaq100()
    #df['Ticker'] = df['Ticker'].str.replace('.', '/')
    symbols = df['Ticker'].values.tolist()
    p = pprint.pformat(symbols, width=79, compact=True, indent=4)
    print(p)

# CSV datafiles (and also used for sql database):
#csv_dir = None
csv_dir = 'data'

sql_filename = 'IB.db'

# database engine:
engine = None

def open_db():
    global engine
    if not csv_dir:
        return True
    if not os.path.isdir(csv_dir):
        print('Directory %s does not exist, please create it.' % csv_dir)
        return False
    use_sqlalchemy = False
    if not use_sqlalchemy:
        import sqlite3
        #db_file = ':memory:'
        db_file = os.path.join(csv_dir, sql_filename)
        engine = sqlite3.connect(db_file)
    else:
        from sqlalchemy import create_engine
        #db_file = 'sqlite:///:memory:'
        #db_file = 'sqlite:///data/' + sql_filename
        db_file = os.path.join('sqlite:///' + csv_dir, sql_filename)
        engine = create_engine(db_file)
    return True

def close_db():
    global engine
    if not csv_dir:
        return
    engine.close()
    engine = None

tables = []

# Get a list of available database tables.
def getDbTables():
    if not engine:
        return []
    dbcurr = engine.cursor()
    dbcurr.execute("SELECT name FROM sqlite_master WHERE type='table';")
    return [table[0] for table in dbcurr.fetchall()]

# weekly and daily data is in one big file, everything else is stored
# on a per-year basis
def getTableName(stock, exchange, year, timespan, onetable):
    if onetable:
        return '%s-%s-%s' % (stock, exchange, timespan)
    return '%s-%s-%d-%s' % (stock, exchange, year, timespan)

# CSV filename, compressed with gzip
def getCsvFilename(table_name):
    return os.path.join(csv_dir, table_name + '.csv.gz')

# Convert IB data into pandas dataframe (df).
def ConvertIB2Dataframe(bars):
    df = ib_insync.util.df(bars)
    df.set_index(['date'], inplace=True)
    return df

def writeIT2(ib, contract, stock, exchange, year, timespan, barSize, duration,
    onetable, check=False):
    table_name = getTableName(stock, exchange, year, timespan, onetable)
    exist = True
    if csv_dir:
        csv_file = getCsvFilename(table_name)
        if not os.path.exists(csv_file):
            exist = False
    if engine and table_name not in tables:
        exist = False
    if check:
        exist = False
    if exist:
        return
    if onetable:
        print(stock, timespan)
    else:
        print(stock, year, timespan)
    bars = ib.reqHistoricalData(contract, endDateTime='%d0101 00:00:00 UTC' % (year + 1),
        durationStr=duration, barSizeSetting=barSize, whatToShow='TRADES', # MIDPOINT
        useRTH=True) #, formatDate=1)
    if not bars:
        return
    df = ConvertIB2Dataframe(bars)
    # Save into CSV file and sql database:
    if csv_dir:
        df.to_csv(csv_file)
    if engine: # and table_name not in tables:
        df.to_sql(table_name, engine, if_exists='replace')
        if table_name not in tables:
            tables.append(table_name)

def writeIT(ib, stock, exchange, currency, hourly=True):
    contract = ib_insync.Stock(stock, exchange, currency)
    #details = ib.reqContractDetails(contract)
    #print(details)
    #if details.Contract.secType != 'STK':
    #    raise
    #if details.symbol != stock or details.localSymbol != stock:
    #    raise
    #if details.exchange != exchange:
    #    raise
    # XXX: write down time of fetching/checking data
    cur_year = int(time.strftime('%Y'))
    writeIT2(ib, contract, stock, exchange, cur_year, 'weekly', '1 week', '40 Y', True)
    writeIT2(ib, contract, stock, exchange, cur_year, 'daily', '1 day', '40 Y', True)
    if not hourly:
        return
    # Find first year of data:
    startYear = 1980
    if csv_dir:
        table_name = getTableName(stock, exchange, cur_year, 'weekly', True)
        csv_file = getCsvFilename(table_name)
        wk = pandas.read_csv(csv_file) # index_col='Date')
        startYear = int(wk['date'][0][:4])
    # Download yearly data:
    for year in range(cur_year, startYear - 1, -1):
        #writeIT2(ib, contract, stock, exchange, year, 'daily', '1 day', '1 Y', False)
        if year >= 2004 and hourly:
            writeIT2(ib, contract, stock, exchange, year, 'hourly', '1 hour', '1 Y', False)

def write_some_stocks(ib):
    writeIT(ib, 'AAPL', 'SMART', 'USD')
    writeIT(ib, 'TSLA', 'SMART', 'USD')
    writeIT(ib, 'TSLA', 'NYSE', 'USD')
    writeIT(ib, 'TSLA', 'ISLAND', 'USD')

def write_some_stocks2(ib):
    # CSCO FTRCQ IEP RDS.B
    stocks = ['APLE', 'BTI', 'CIM', 'D', 'DUK', 'ENB', 'EPD',
        'EPR', 'ETRN', 'FAX', 'GE', 'GTY', 'HBI', 'JNJ', 'KHC', 'LMT',
        'LTC', 'M', 'MA', 'MAIN', 'MMM', 'MMP', 'MO', 'MPW', 'OPI',
        'OZK', 'PM', 'PPL', 'PRU', 'SKT', 'TEVA', 'TSN', 'UHS', 'V',
        'VLO', 'WB', 'WSR']
    for stock in stocks:
        writeIT(ib, stock, 'SMART', 'USD')

# https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average
def write_dow_stocks(ib):
    dow = ['NYSE:MMM', 'NYSE:AXP', 'AMGN', 'AAPL', 'NYSE:BA', 'NYSE:CAT', 'NYSE:CVX', 'CSCO',
        'NYSE:KO', 'NYSE:DOW', 'NYSE:GS', 'NYSE:HD', 'HON', 'NYSE:IBM', 'INTC',
        'NYSE:JNJ', 'NYSE:JPM', 'NYSE:MCD', 'NYSE:MRK', 'MSFT', 'NYSE:NKE', 'NYSE:PG',
        'NYSE:CRM', 'NYSE:TRV', 'NYSE:UNH', 'NYSE:VZ', 'NYSE:V', 'WBA', 'NYSE:WMT', 'NYSE:DIS']
    for stock in dow:
        #exchange = 'SMART'
        exchange = 'ISLAND'
        #exchange = 'NASDAQ'
        if stock[:5] == 'NYSE:':
            stock = stock[5:]
            exchange = 'NYSE'
        writeIT(ib, stock, exchange, 'USD', False)

def write_sp500_stocks(ib):
    nyse = ['AAL', 'CSCO', 'KEYS', 'LIN', 'META', 'MNST', 'WELL']
    disable = ['VICI',]
    for stock in SP500:
        stock = stock.replace('.', ' ')
        exchange = 'SMART'
        if stock in nyse:
            exchange = 'NYSE'
        if stock in disable:
            continue
        writeIT(ib, stock, exchange, 'USD', False)

def write_nasdaq_stocks(ib):
    # https://en.wikipedia.org/wiki/NASDAQ-100#Components
    for stock in NASDAQ100:
        exchange = 'ISLAND'
        #exchange = 'NASDAQ'
        writeIT(ib, stock, exchange, 'USD', False)

def getSPX():
    return Index('SPX', 'CBOE', 'USD', description='SP500 Index')

def getVIX():
    return Index('VIX', 'CBOE', 'USD', description='CBOE Volatility Index')

def getADNYSE():
    return Index('AD-NYSE', 'NYSE', 'USD', description='NYSE Advance Decline Index')

def getDAX():
    return Index('DAX', 'EUREX', 'EUR', description='DAX Performance Index')

def getVDAX():
    return Index('VDAX', 'EUREX', 'EUR', description='German VDAX Volatility Index')

def getSTOXX():
    return Index('ESTX50', 'EUREX', 'EUR', description='Dow Jones Euro STOXX50')

def getVSTOXX():
    return Index('V2TX', 'EUREX', 'EUR', description='VSTOXX Volatility Index')

def getHSI():
    return Index('HSI', 'HKFE', 'HKD', description='Hang Seng Index')

def getVHSI():
    return Index('VHSI', 'HKFE', 'HKD', description='Hang Seng Volatility Index')

def getMiniHSI():
    return Index('MHI', 'HKFE', 'HKD', description='Mini Hang Seng Index')

def getEURUSD():
    return Forex('EURUSD')

def usage():
    print('stock-hist-data-download.py ' +
        '[--list-index][--data-dir=data]' +
        '[--host=127.0.0.1][--port=7496][--client-id=0]' +
        '[--help][--verbose][--debug][--quiet]')

def show_account(ib):
    #print([v for v in ib.accountValues() if v.tag == 'NetLiquidationByCurrency' and v.currency == 'BASE'])
    if True:
        portfolio = ib.portfolio()
        if portfolio:
            print('Portfolio:')
            for p in portfolio:
                print(p)
    if True:
        positions = ib.positions()
        if positions:
            print('Positions:')
            for p in positions:
                print(p)
    if True:
        trades = ib.trades()
        if trades:
            print('Trades:')
            for t in trades:
                print(t)
    if True:
        orders = ib.orders()
        if orders:
            print('Orders:')
            for o in orders:
                print(o)

def main(argv):
    global tables, csv_dir
    import getopt
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
        elif opt == '--data-dir':
            if arg in ('', 'None'):
                csv_dir = None
            else:
                csv_dir = arg
        elif opt == '--list-index':
            print_sp500()
            print_nasdaq100()
            sys.exit(0)
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
        ib.connect(host, port, clientId=client_id) # account
    except ConnectionRefusedError:
        sys.exit(1)

    #show_account(ib)

    if not open_db():
        sys.exit(3)
    tables = getDbTables()
    #print(tables)
    #trades = pd.read_sql(trades_query, self.dbconn)

    #write_some_stocks(ib)
    #write_some_stocks2(ib)
    write_dow_stocks(ib)
    write_sp500_stocks(ib)
    write_nasdaq_stocks(ib)

    #ib.sleep(10)
    ib.disconnect()
    close_db()

if __name__ == '__main__':
    main(sys.argv[1:])
