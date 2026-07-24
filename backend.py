import os
import pandas as pd
import ccxt
import google.generativeai as genai
import sqlite3
import numpy as np
from dotenv import load_dotenv

# --- CONFIGURATION ---
# The API key is read from the environment (copy .env.example to .env and fill
# it in, or export GEMINI_API_KEY). Never hardcode credentials in source.
load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_API_KEY)

class BinanceDataHandler:
    def __init__(self):
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        self.markets = self.exchange.load_markets()

    def get_all_symbols(self):
        symbols = [s for s in self.markets if '/USDT' in s and ':USDT' in s]
        return sorted(symbols)

    def fetch_current_prices(self, symbols_list):
        """Fetches live prices for a list of symbols instantly."""
        if not symbols_list: return {}
        try:
            tickers = self.exchange.fetch_tickers(symbols_list)
            return {symbol: data['last'] for symbol, data in tickers.items()}
        except:
            return {}

    def fetch_market_data(self, symbol, timeframe='1m', limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # --- INDICATORS ---
            df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
            
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).fillna(0)
            loss = (-delta.where(delta < 0, 0)).fillna(0)
            avg_gain = gain.rolling(window=14, min_periods=1).mean()
            avg_loss = loss.rolling(window=14, min_periods=1).mean()
            rs = avg_gain / avg_loss
            df['RSI'] = 100 - (100 / (1 + rs))
            df['RSI'] = df['RSI'].fillna(50)

            df['Signal'] = 0
            df.loc[df['RSI'] < 30, 'Signal'] = 1  # Buy
            df.loc[df['RSI'] > 70, 'Signal'] = -1 # Sell
            
            return df
        except Exception as e:
            print(f"Error: {e}")
            return pd.DataFrame()

    def analyze_market_with_ai(self, df):
        if df.empty: return "No Data"
        model = genai.GenerativeModel('gemini-flash-latest')
        latest_data = df.tail(10).to_string()
        current_price = df['close'].iloc[-1]
        prompt = f"Analyze BTC data: {latest_data}. Price: {current_price}. Trend? Support/Resistance? BUY/SELL signal?"
        try:
            return model.generate_content(prompt).text
        except Exception as e:
            return f"AI Error: {e}"

class PaperTradingWallet:
    def __init__(self, initial_balance=10000):
        self.db_name = "trading_data.db"
        self.init_db(initial_balance)
        self.balance = 0
        self.load_balance()

    def init_db(self, initial_balance):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS wallet (id INTEGER PRIMARY KEY, balance REAL)')
        
        # Portfolio now tracks Entry Price to calculate PnL
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio (
                symbol TEXT PRIMARY KEY, 
                amount REAL,
                entry_price REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                symbol TEXT,
                side TEXT,
                price REAL,
                amount REAL,
                pnl REAL
            )
        ''')
        
        cursor.execute('SELECT count(*) FROM wallet')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO wallet (balance) VALUES (?)', (initial_balance,))
            conn.commit()
        conn.close()

    def load_balance(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM wallet LIMIT 1')
        self.balance = cursor.fetchone()[0]
        conn.close()

    def get_position(self, symbol):
        """Returns (amount, entry_price) for a symbol."""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT amount, entry_price FROM portfolio WHERE symbol = ?', (symbol,))
        row = cursor.fetchone()
        conn.close()
        return row if row else (0.0, 0.0)

    def get_all_positions(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT symbol, amount, entry_price FROM portfolio WHERE amount != 0')
        data = cursor.fetchall()
        conn.close()
        # Convert to list of dicts
        return [{"symbol": r[0], "amount": r[1], "entry_price": r[2]} for r in data]

    def execute_trade(self, symbol, current_price, amount_usdt, side):
        """
        Handles Longs, Shorts, and Closing positions efficiently.
        side: 'LONG' (Buy) or 'SHORT' (Sell)
        """
        self.load_balance()
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # 1. Calculate Amount in Crypto
        qty = amount_usdt / current_price
        
        # 2. Get Current Position
        curr_amt, curr_entry = self.get_position(symbol)
        
        realized_pnl = 0.0
        new_amt = curr_amt
        new_entry = curr_entry
        trade_desc = ""

        # --- LOGIC: LONG (BUY) ---
        if side == "LONG":
            cost = amount_usdt
            if self.balance < cost: return "❌ Insufficient Balance"
            
            # If we are Short, buying closes the position
            if curr_amt < 0:
                # Closing Short: Profit = (Entry - Current) * Qty
                # We are covering 'qty' amount of short
                cover_qty = min(abs(curr_amt), qty)
                pnl = (curr_entry - current_price) * cover_qty
                realized_pnl += pnl
                new_amt += cover_qty # Short (-5) + Buy (2) = -3
                trade_desc = "📉 Covered Short"
                
                # If we flipped to Long (bought more than short size)
                remaining_buy = qty - cover_qty
                if remaining_buy > 0:
                    new_amt += remaining_buy
                    new_entry = current_price # New entry for the net long part
                    trade_desc = "🔄 Flipped to Long"
            
            else:
                # Adding to Long (Weighted Average Entry)
                total_cost = (curr_amt * curr_entry) + (qty * current_price)
                new_amt += qty
                new_entry = total_cost / new_amt
                trade_desc = "📈 Added to Long"
            
            self.balance -= cost # Pay for the trade
        
        # --- LOGIC: SHORT (SELL) ---
        elif side == "SHORT":
            # For shorting, we assume 1x leverage margin logic (simplified)
            # You need 'amount_usdt' collateral to open this short
            if self.balance < amount_usdt: return "❌ Insufficient Collateral"
            
            # If we are Long, selling closes the position
            if curr_amt > 0:
                # Closing Long: Profit = (Current - Entry) * Qty
                close_qty = min(curr_amt, qty)
                pnl = (current_price - curr_entry) * close_qty
                realized_pnl += pnl
                new_amt -= close_qty
                trade_desc = "💰 Closed Long"
                
                # If flipped to Short
                remaining_sell = qty - close_qty
                if remaining_sell > 0:
                    new_amt -= remaining_sell # Becomes negative
                    new_entry = current_price
                    trade_desc = "🔄 Flipped to Short"
            else:
                # Adding to Short (Weighted Average Entry)
                # Short amount is negative, but we track size positively for avg math
                total_val = (abs(curr_amt) * curr_entry) + (qty * current_price)
                new_amt -= qty # Make it more negative
                new_entry = total_val / abs(new_amt)
                trade_desc = "📉 Added to Short"
            
            self.balance -= amount_usdt # Locked collateral

        # 3. Apply Updates
        self.balance += realized_pnl # Add PnL to cash
        
        cursor.execute('UPDATE wallet SET balance = ? WHERE id = 1', (self.balance,))
        cursor.execute('INSERT OR REPLACE INTO portfolio (symbol, amount, entry_price) VALUES (?, ?, ?)', 
                       (symbol, new_amt, new_entry))
        cursor.execute('INSERT INTO trades (symbol, side, price, amount, pnl) VALUES (?, ?, ?, ?, ?)',
                       (symbol, trade_desc, current_price, qty, realized_pnl))
        
        conn.commit()
        conn.close()
        return f"✅ {trade_desc} | Size: {qty:.4f}"