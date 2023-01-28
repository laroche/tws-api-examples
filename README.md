TWS API examples for Interactive Brokers (IB)
=============================================

[Interactive Brokers (IB)](https://www.interactivebrokers.com/en/home.php) allows to connect with their
trading software [Trader Workstation (TWS)](https://www.interactivebrokers.com/en/trading/tws.php)
through their [TWS API](https://interactivebrokers.github.io/tws-api/).


Enable TWS API access for your local computer
---------------------------------------------

You first need to start TWS on your computer and within the settings menue you have to
enable TWS API access for your "localhost" network interface (127.0.0.1) on port 7496.
For paper trading (demo/test account) this is port 7497 per default.
This allows to run scripts on the same machine you run TWS on.

Instead of IB TWS, you can also use IB Gateway. This uses port 4002 per default for
paper trading (demo/test account) and 4001 for an active/real/live account.

Check this: <https://interactivebrokers.github.io/tws-api/initial_setup.html>.

Once you start scripts conneting to your TWS, you can see also a new tab "API" on your TWS.


Official TWS API software from IB
---------------------------------

Official TWS API software from Interactive Brokers can be found on
<https://www.interactivebrokers.com/en/trading/ib-api.php>.

Discussions around the TWS API are best on <https://groups.io/g/twsapi>.

Please also check the FAQ at: <https://dimon.ca/dmitrys-tws-api-faq/>.


Install ib_insync for python
----------------------------

[ib_insync](https://github.com/erdewit/ib_insync) ist another python API to connect to your TWS
with docu at <https://ib-insync.readthedocs.io/> and
discussions at <https://groups.io/g/insync>.

To install ib_insync, first install python3 and then run:
<pre>
pip3 install ib_insync
</pre>

To update ib_insync later on, run:
<pre>
pip3 install --upgrade ib_insync
</pre>


python library pandas
---------------------

[pandas](https://pandas.pydata.org/) is a useful additional python library
for data analysis and manipulation.

Install on Debian or Ubuntu Linux with:
<pre>
sudo apt-get install python3-pandas
</pre>

Or you can install via pip3:
<pre>
pip3 install pandas
</pre>

For updates run:
<pre>
pip3 install --upgrade pandas
</pre>


historic stock data download
----------------------------

Example script which downloads historic stock data for all
companies of the DOW, SP500 and Nasdaq100 indices.

The data is stored into the subdirectory "data" per default,
so please create this directory before calling this script.

See [stock-hist-data-download.py](stock-hist-data-download.py).

How to update the index list of the SP500 and Nasdaq100:
<pre>
python3 stock-hist-data-download.py --list-index > TMPFILE
diff -u stock-hist-data-download.py TMPFILE
</pre>


links to similar / further projects
-----------------------------------

- automate running IB TWS: <https://github.com/IbcAlpha/IBC>
   - <https://groups.io/g/ibcalpha>
- Github topics to look at:
   - <https://github.com/topics/interactive-brokers>
   - <https://github.com/topics/tws>
   - <https://github.com/topics/tws-api>
   - <https://github.com/topics/ib-api>
   - <https://github.com/topics/ibapi>
- IB ruby: <https://github.com/ib-ruby>
- <https://github.com/andrey-zotov/ib_console>
- <https://github.com/pavanmullapudy/InteractiveBrokers_TWS_API>
   - <https://github.com/pavanmullapudy/InteractiveBrokers_TWS_API/blob/master/futures%20and%20options/NIFTY%20ORB%20Trading%20System/tech_indicators.py>


IB flex queries
---------------

A bit different to the TWS API are flex queries and downloading/parsing of them.

Here some projects around this:

- <https://github.com/MikePia/structjour>


