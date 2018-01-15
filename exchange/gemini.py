import requests
import keyring
import base64
import hmac
import time
import json
import datetime

from hashlib import sha384
from decimal import Decimal
from collections import OrderedDict


BASE_URL = "https://api.sandbox.gemini.com"
API_VERSION = "v1"

KEYRING_NAMESPACE = "gemini_sandbox"
KEYRING_API_KEY = "api_key"
KEYRING_API_SECRET = "api_secret"

def get_timestamp_ms():
    # TODO: replace `time.time()` with something more accurate in ms
    return int(time.time() * 1000)

def unix_to_readable(unix):
    if isinstance(unix, str):
        unix = Decimal(unix)
    dt = datetime.datetime.fromtimestamp(unix)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def parse_response(response):
    data = json.loads(response.text)
    if 'result' in data and data['result'] == 'error':
        raise RuntimeError('{}: {}'.format(data['reason'], data['message']))
    return data
    

def public_req(url_path, parameters):
    url = "{}/{}/{}".format(BASE_URL, API_VERSION, url_path)
    response = requests.request("GET", url, params=parameters)
    return parse_response(response)


def private_req(url_path, parameters):
    version_path = '/{}/{}'.format(API_VERSION, url_path)
    parameters['request'] = version_path
    parameters['nonce'] = get_timestamp_ms()

    # Base 64 encode the parameters
    param_json = json.dumps(parameters)
    b64 = base64.b64encode(param_json.encode('utf-8'))

    api_secret = keyring.get_password(KEYRING_NAMESPACE, KEYRING_API_SECRET)
    signature = hmac.new(api_secret.encode('utf-8'), b64, sha384).hexdigest()

    api_key = keyring.get_password(KEYRING_NAMESPACE, KEYRING_API_KEY)
    headers = {
        'Content-Type': 'text/plain',
        'Content-Length': '0',
        'X-GEMINI-APIKEY': api_key,
        'X-GEMINI-PAYLOAD': b64,
        'X-GEMINI-SIGNATURE': signature,
        'Cache-Control': 'no-cache',
    }

    url = '{}{}'.format(BASE_URL, version_path) 
    response = requests.request('POST', url, headers=headers)
    return parse_response(response)


def new_order(symbol, amount, price, side, client_id=None):
    '''
    Place a new order.  Total order price is `amount` * `price`
    symbol: { "btcusd", "ethusd", "ethbtc" }
    amount: How much to buy
    price: Price at which to buy
    side: "buy" or "sell"
    client_id: client order id for later lookup (optional)
    '''
    # TODO: support order execution options
    # https://docs.gemini.com/rest-api/?python#new-order

    # TODO: Add client order ID support
    params = {
        'symbol': "{}".format(symbol),
        'amount': "{}".format(amount),
        'price': "{}".format(price),
        'side': side,
        'type': 'exchange limit',
        'options': [],
    }

    if client_id:
        params['client_order_id'] = client_id

    return private_req("order/new", params)


def read_field(data, field, ctor=None):
    if field in data:
        return ctor(data[field]) if ctor else data[field]
    return None


class Symbols(object):
    def __init__(self):
        response = public_req("symbols")
        self.supported = json.loads(response.text)


class Volume(object):
    def __init__(self, data):
        if isinstance(data, str):
            data = json.loads(data)

        self.symbols = {}
        for key, value in data.items():
            if key == 'timestamp':
                self.timestamp = Decimal(value)
            else:
                self.symbols[key] = Decimal(value)

    def __str__(self):
        sym_str = ', '.join(['{}: {}'.format(k, v) for k, v in self.symbols.items()])
        return 'Volume = {}, timestamp: {}'.format(sym_str, self.timestamp)


class Trade(object):
    def __init__(self, data):
        self.timestamp = Decimal(data['timestamp'])
        self.timestampms = Decimal(data['timestampms']) 
        self.id = int(data['tid'])
        self.price = Decimal(data['price'])
        self.amount = Decimal(data['amount'])
        self.exchange = data['exchange']
        self.type = data['type']
        self.broken = read_field(data, 'broken', bool)

    def __str__(self):
        ts = unix_to_readable(self.timestamp)
        return 'Transaction {}\n\tPrice: {}\n\tAmount: {}\n\tTimestamp: {}'.format(
            self.id, self.price, self.amount, ts)


class Order(object):
    def __init__(self, data):
        self.price = Decimal(data['price'])
        self.amount = read_field(data, 'amount', Decimal)
        self.id = read_field(data, 'order_id', Decimal)
        self.client_id = read_field(data, 'client_order_id', Decimal)
        self.symbol = read_field(data, 'symbol')
        self.exchange = read_field(data, 'exchange')
        self.avg_execution_price = read_field(data, 'avg_execution_price', Decimal)
        self.side = read_field(data, 'side')
        self.type = read_field(data, 'type')
        self.options = read_field(data, 'options')
        self.timestamp = read_field(data, 'timestamp', Decimal)
        self.timestamp_ms = read_field(data, 'timestampms', Decimal)
        self.is_live = read_field(data, 'is_live', bool)
        self.is_cancelled = read_field(data, 'is_cancelled', bool)
        self.executed_amount = read_field(data, 'executed_amount', Decimal)
        self.remaining_amount = read_field(data, 'remaining_amount', Decimal)
        self.original_amount = read_field(data, 'original_amount', Decimal)
        

    def __str__(self):
        if self.amount:
            return 'Amount: {}, Price: {}'.format(self.amount, self.price)
        # else
        return "Order {} ({})\n\tAmount: {}\n\tPrice: {}\n\tSide: {}\n\t"\
            "Type: {}\n\tSubmitted: {}\n\tLive: {}".format(
            self.client_id, self.id, self.original_amount, self.price,
            self.side, self.type, unix_to_readable(self.timestamp),
            self.is_live)


class TickerStatus(object):
    def __init__(self, data):
        self.bid = Decimal(data['bid'])
        self.ask = Decimal(data['ask'])
        self.last_price = Decimal(data['last'])
        self.volume = read_field(data, 'volume', Volume)
        

    def __str__(self):
        return('Bid = {}, Ask = {}, Last price = {}, {}'.format(
            self.bid, self.ask, self.last_price, self.volume))


class CurrencyBalance(object):
    def __init__(self, data):
        self.currency = data['currency']
        self.amount = Decimal(data['amount'])
        self.available = Decimal(data['available'])
        self.withdrawable = Decimal(data['availableForWithdrawal'])

    def __str__(self):
        return 'Currency {}\n\tAmount: {}\n\tAvailable: {}\n\tWithdrawable: {}'\
            .format(self.currency.upper(), self.amount, self.available,
            self.withdrawable)


class Ticker(object):
    def __init__(self, symbol):
        '''
        symbol: {"btcusd", "ethusd", "ethbtc"}
        '''
        self.symbol = symbol.lower()
        self.last_request_ts = None
        self.last_status = None

    def update(self):
        self.last_request_ts = get_timestamp_ms()
        response = public_req("pubticker/{}".format(self.symbol))
        self.last_trade = TickerStatus(response)
        return self.last_trade


class TradeHistory(object):
    def __init__(self, symbol, limit_trades=50, include_breaks=False):
        self.symbol = symbol
        self.limit_trades = limit_trades
        self.include_breaks = include_breaks
        self.last_request_ts = None
        self.trades = None

    def update(self, timestamp=None):
        self.last_request_ts = get_timestamp_ms()
        params = {
            'limit_trades': self.limit_trades,
            'include_breaks': '1' if self.include_breaks else '0',
        }
        if timestamp:
            params['timestamp'] = timestamp

        data = public_req('trades/{}'.format(self.symbol), params)
        self.trades = [Trade(entry) for entry in data]

    def __str__(self):
        return '\n'.join([str(t) for t in self.trades]) \
            if self.trades else 'Not available'


class OrderBook(object):
    def __init__(self, symbol, limit_bids=50, limit_asks=50):
        '''
        symbol: {"btcusd", "ethusd", "ethbtc"}
        limit_bids: # of bids to get per request
        limit_asks: # of asks to get per request
        '''
        self.symbol = symbol
        self.limit_bids = limit_bids
        self.limit_asks = limit_asks
        self.bids = None
        self.asks = None
        self.last_request_ts = None


    def update(self):
        self.last_request_ts = get_timestamp_ms()
        params = {
            'limit_bids': self.limit_bids,
            'limit_asks': self.limit_asks,
        }
        data = public_req('book/{}'.format(self.symbol), params)
        self.bids = [Order(entry) for entry in data['bids']]
        self.asks = [Order(entry) for entry in data['asks']]


class TradeManager(object):
    def __init__(self, symbol):
        self.order_book = OrderBook(symbol)
        self.symbol = symbol
        self.buy_orders = OrderedDict()
        self.sell_orders = OrderedDict()

    def place_buy(self, amount, price):
        data = new_order(self.symbol, amount, price, "buy")
        order = Order(data)
        self.buy_orders[order.id] = order
        return order

    def place_sell(self, amount, price):
        data = new_order(self.symbol, amount, price, "sell")
        order = Order(data)
        self.sell_orders[order.id] = order
        return order

    def cancel(self, order):
        params = {
            'order_id': order.id,
        }
        data = private_req('order/cancel', params)
        order = Order(data)
        self._update_order(order)

        return order

    def cancel_session(self):
        private_req('order/cancel/session', {})
        self.buy_orders = []
        self.sell_orders = []

    def cancel_all(self):
        private_req('orer/cancel/all', {})
        self.buy_orders = []
        self.sell_orders = []

    def get_order_status(self, order):
        params = {
            'order_id': order.id
        }
        data = private_req('order/status', params)
        order = Order(data)
        self._update_order(order)
        return order

    def get_active_orders(self):
        result = []
        data = private_req('orders', {})
        for entry in data:
            order = Order(entry)
            self._update_order(order)
            result.append(order)
        # Should we filter the result to just the orders of this symbol?
        return result

    # TODO: implement getting past trades and trade volume
    # TODO: implement current auction and auction history APIs

    def _update_order(self, order):
        if order.symbol != self.symbol:
            return

        if order.side == 'buy':
            self.buy_orders[order.id] = order
        elif order.side == 'sell':
            self.sell_orders[order.id] = order
        else:
            raise RuntimeError('Unkown order side: ' + order.side)

class FundManager(object):
    def __init__(self):
        self.balances = None
        self.last_update = None
        self.withdrawals = []

    def get_balances(self):
        self.last_update = get_timestamp_ms()
        data = private_req('balances', {})
        self.balances = [CurrencyBalance(entry) for entry in data]
        return self.balances

    def withdraw(self, address, currency, amount):
        '''
        address: address to send funds to. note: address needs to already be
        whitelisted on the account
        currency: {"btc", "eth"}
        amount: how much to transfer
        '''
        params = {
            'address': address,
            'amount': amount,
        }
        data = private_req('withdraw/{}'.format(currency), params)
        self.withdrawals.append(data)
        return data

    # TODO: implement New Deposit Address API
