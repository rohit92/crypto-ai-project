import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import time
from backend import BinanceDataHandler, PaperTradingWallet

st.set_page_config(page_title="Future Trading Terminal", layout="wide", page_icon="📊")

# --- INIT ---
if 'handler' not in st.session_state: st.session_state.handler = BinanceDataHandler()
if 'wallet' not in st.session_state: st.session_state.wallet = PaperTradingWallet()

# --- SIDEBAR ---
st.sidebar.title("⚙️ Market Watch")
all_symbols = st.session_state.handler.get_all_symbols()
default_idx = all_symbols.index('BTC/USDT:USDT') if 'BTC/USDT:USDT' in all_symbols else 0
symbol = st.sidebar.selectbox("Select Asset", all_symbols, index=default_idx)
timeframe = st.sidebar.selectbox("Timeframe", ["1m", "5m", "15m", "1h"])

# REFRESH CONTROL
# We use this variable to control the 'fragment' update speed
refresh_rate = st.sidebar.slider("Refresh Speed (s)", 1, 60, 2)
is_live = st.sidebar.checkbox("🔴 Live Updates", value=True)

# --- HEADER (Static - Won't Blink) ---
st.title(f"🚀 {symbol} Futures Terminal")

# --- THE LIVE FRAGMENT (Only this part updates) ---
@st.fragment(run_every=refresh_rate if is_live else None)
def render_live_dashboard():
    handler = st.session_state.handler
    wallet = st.session_state.wallet

    # 1. Fetch Data
    df = handler.fetch_market_data(symbol, timeframe)
    current_price = df['close'].iloc[-1] if not df.empty else 0.0

    # 2. Portfolio & PnL Calc
    positions = wallet.get_all_positions()
    held_symbols = [p['symbol'] for p in positions]
    live_prices = handler.fetch_current_prices(held_symbols)
    if symbol not in live_prices: live_prices[symbol] = current_price
    
    total_equity = wallet.balance
    portfolio_data = []

    for pos in positions:
        sym = pos['symbol']
        amt = pos['amount']
        entry = pos['entry_price']
        live_px = live_prices.get(sym, entry)
        
        if amt > 0: # LONG
            pnl = (live_px - entry) * amt
            side = "LONG 🟢"
        else: # SHORT
            pnl = (entry - live_px) * abs(amt)
            side = "SHORT 🔴"
        
        total_equity += pnl
        portfolio_data.append({
            "Asset": sym.split('/')[0], "Side": side, "Size": f"{abs(amt):.4f}",
            "Entry": f"${entry:.2f}", "Mark": f"${live_px:.2f}", "PnL": pnl
        })

    # 3. Top Metrics Row
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current Price", f"${current_price:.2f}")
    c2.metric("Available Balance", f"${wallet.balance:.2f}")
    c3.metric("Total Equity", f"${total_equity:.2f}", delta=f"{total_equity - 10000:.2f} PnL")
    
    rsi_val = df['RSI'].iloc[-1] if not df.empty else 50
    c4.metric("RSI Signal", f"{rsi_val:.1f}", delta="Buy Zone" if rsi_val < 30 else "Sell Zone" if rsi_val > 70 else "Neutral")

    # 4. Main Layout
    col_chart, col_trade = st.columns([3, 1])

    with col_chart:
        if not df.empty:
            fig = go.Figure()
            # CANDLES
            fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name="Price"))
            # EMA (Trend Line)
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_20'], line=dict(color='orange', width=1), name="EMA 20"))
            
            # SIGNALS
            buys = df[df['Signal'] == 1]
            sells = df[df['Signal'] == -1]
            fig.add_trace(go.Scatter(x=buys['timestamp'], y=buys['low'], mode='markers', marker=dict(symbol='triangle-up', color='#00FF00', size=14), name='Buy'))
            fig.add_trace(go.Scatter(x=sells['timestamp'], y=sells['high'], mode='markers', marker=dict(symbol='triangle-down', color='#FF0000', size=14), name='Sell'))
            
            fig.update_layout(height=550, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)

        # PORTFOLIO TABLE
        st.subheader("💼 Positions")
        if portfolio_data:
            df_pnl = pd.DataFrame(portfolio_data)
            def color_pnl(val): return f'color: {"green" if val > 0 else "red" if val < 0 else "white"}'
            st.dataframe(df_pnl.style.applymap(color_pnl, subset=['PnL']), use_container_width=True)
        else:
            st.info("No active trades.")

    with col_trade:
        st.subheader("⚡ Quick Trade")
        curr_pos = wallet.get_position(symbol)
        amt_held = curr_pos[0]
        
        # Position Indicator
        if amt_held > 0: st.success(f"LONG {amt_held:.4f}")
        elif amt_held < 0: st.error(f"SHORT {abs(amt_held):.4f}")
        else: st.caption("No Position")

        trade_amt = st.number_input("Size (USDT)", value=100.0, step=50.0)
        
        # We use st.columns for buttons to keep them side-by-side
        b1, b2 = st.columns(2)
        if b1.button("🟢 BUY / LONG", use_container_width=True):
            res = wallet.execute_trade(symbol, current_price, trade_amt, "LONG")
            if "✅" in res: st.toast(res, icon="✅")
            else: st.error(res)
            time.sleep(0.5)
            st.rerun() # Force instant update after trade

        if b2.button("🔴 SELL / SHORT", use_container_width=True):
            res = wallet.execute_trade(symbol, current_price, trade_amt, "SHORT")
            if "✅" in res: st.toast(res, icon="✅")
            else: st.error(res)
            time.sleep(0.5)
            st.rerun()

        st.markdown("---")
        if st.button("🧠 AI Analysis", use_container_width=True):
            with st.spinner("Analyzing..."):
                analysis = handler.analyze_market_with_ai(df)
                st.info(analysis)

# --- RUN THE FRAGMENT ---
render_live_dashboard()