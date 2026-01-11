import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- Page Config ---
st.set_page_config(page_title="PBOC Fixing Model", layout="wide")

# --- Custom Styles (Dark Mode for Traders) ---
st.markdown("""
<style>
    .big-font { font-size:24px !important; font-weight: bold; }
    .metric-box { background-color: #1e1e1e; padding: 15px; border-radius: 5px; border: 1px solid #333; }
    .up-green { color: #00ff00; }
    .down-red { color: #ff4b4b; }
</style>
""", unsafe_allow_html=True)

# --- Constants: Approximate CFETS Weights (2025/2026 Proxy) ---
# Note: These weights are proxies. Real weights are proprietary and change annually.
WEIGHTS = {
    'USD': 0.198, # Base
    'EUR': 0.180,
    'JPY': 0.090,
    'KRW': 0.080,
    'GBP': 0.030,
    'AUD': 0.050,
    # Others bundled or ignored for this simplified proxy
}

# --- Functions ---

@st.cache_data(ttl=300)
def get_market_data():
    """Fetches overnight moves for major basket currencies."""
    tickers = {
        'EURUSD': 'EURUSD=X',
        'USDJPY': 'JPY=X',
        'GBPUSD': 'GBPUSD=X',
        'AUDUSD': 'AUDUSD=X',
        'USDCNY': 'CNY=X' # Used for reference only
    }
    
    data = {}
    try:
        # Fetch last 2 days to get closes
        df = yf.download(list(tickers.values()), period="5d", interval="1d", progress=False)['Close']
        
        # Calculate Overnight Change (From previous Close to Current Live/Pre-market)
        # Note: In a real prop desk, you would hook this to Bloomberg API (blpapi)
        # Here we compare the last Close vs the Close before it to simulate the overnight move
        
        last_close = df.iloc[-1]
        prev_close = df.iloc[-2]
        
        changes = (last_close - prev_close) / prev_close
        
        data = {
            'EURUSD': {'rate': last_close[tickers['EURUSD']], 'chg': changes[tickers['EURUSD']]},
            'USDJPY': {'rate': last_close[tickers['USDJPY']], 'chg': changes[tickers['USDJPY']]},
            'GBPUSD': {'rate': last_close[tickers['GBPUSD']], 'chg': changes[tickers['GBPUSD']]},
            'AUDUSD': {'rate': last_close[tickers['AUDUSD']], 'chg': changes[tickers['AUDUSD']]},
        }
    except Exception as e:
        st.error(f"Data Feed Error: {e}")
        return None
        
    return data

def calculate_basket_impact(prev_fix, market_data):
    """
    Calculates the theoretical USDCNY move required to keep the basket stable.
    Logic: If Non-USD currencies weaken vs USD, USDCNY must rise (CNY weaken) 
    to maintain CFETS index stability.
    """
    if not market_data:
        return 0.0

    # Simplified Basket Logic (The "Theoretical" Component)
    # If EURUSD drops 1% (USD stronger), USDCNY needs to rise roughly (Weight_EUR / Weight_USD) * 1%
    
    impact_pips = 0.0
    
    # EUR Impact (Inverse: EUR down -> USDCNY Up)
    eur_move = market_data['EURUSD']['chg']
    impact_pips -= (eur_move * (WEIGHTS['EUR'] / (1 - WEIGHTS['USD']))) * prev_fix * 10000

    # JPY Impact (Direct: USDJPY Up -> USDCNY Up)
    jpy_move = market_data['USDJPY']['chg']
    impact_pips += (jpy_move * (WEIGHTS['JPY'] / (1 - WEIGHTS['USD']))) * prev_fix * 10000
    
    # GBP Impact (Inverse)
    gbp_move = market_data['GBPUSD']['chg']
    impact_pips -= (gbp_move * (WEIGHTS['GBP'] / (1 - WEIGHTS['USD']))) * prev_fix * 10000

    return impact_pips

# --- UI Layout ---

st.title("🇨🇳 PBOC Fixing Predictor (USD/CNY)")
st.markdown("Proprietary model for estimating the daily Central Parity Rate.")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Inputs")
    st.info("Enter the 4:30 PM CST Closing Rate from yesterday.")
    
    # Input: Previous Close
    prev_close = st.number_input("Prev Day Official Close (4:30 PM)", value=6.9850, step=0.0001, format="%.4f")
    prev_fix = st.number_input("Prev Day Fixing", value=6.9820, step=0.0001, format="%.4f")
    
    st.markdown("---")
    st.subheader("2. Policy Override")
    
    ccf_input = st.slider(
        "Counter-Cyclical Factor (CCF) (Pips)", 
        min_value=-100, 
        max_value=100, 
        value=-10,
        help="Positive = PBOC smoothing depreciation (Lifting Fix). Negative = PBOC smoothing appreciation (Lowering Fix)."
    )
    
    st.markdown("*Note: Recently PBOC has been using negative CCF to slow CNY appreciation.*")

# Fetch Data
market_data = get_market_data()

with col2:
    st.subheader("3. Overnight Basket Moves")
    if market_data:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("EUR/USD", f"{market_data['EURUSD']['rate']:.4f}", f"{market_data['EURUSD']['chg']:.2%}")
        c2.metric("USD/JPY", f"{market_data['USDJPY']['rate']:.2f}", f"{market_data['USDJPY']['chg']:.2%}")
        c3.metric("GBP/USD", f"{market_data['GBPUSD']['rate']:.4f}", f"{market_data['GBPUSD']['chg']:.2%}")
        c4.metric("AUD/USD", f"{market_data['AUDUSD']['rate']:.4f}", f"{market_data['AUDUSD']['chg']:.2%}")
    else:
        st.warning("Market data unavailable. Using neutral basket assumption.")

    st.markdown("---")
    
    # --- Calculation Engine ---
    
    # Component A: Market Supply/Demand (Close vs Prev Fix)
    # The fixing moves partially towards the close.
    gap_pips = (prev_close - prev_fix) * 10000
    
    # Component B: Basket Impact
    basket_pips = calculate_basket_impact(prev_fix, market_data)
    
    # Component C: CCF (Manual Input)
    ccf_pips = ccf_input
    
    # Total Move
    total_change_pips = gap_pips + basket_pips + ccf_pips
    predicted_fix = prev_fix + (total_change_pips / 10000)
    
    # --- Display Results ---
    st.subheader("4. Prediction Model")
    
    res_col1, res_col2 = st.columns(2)
    
    with res_col1:
        st.markdown(f"""
        <div class="metric-box">
            <span style="color:#aaa">Theoretical Fix (No CCF)</span><br>
            <span class="big-font">{(predicted_fix - (ccf_pips/10000)):.4f}</span>
        </div>
        """, unsafe_allow_html=True)
        
    with res_col2:
         st.markdown(f"""
        <div class="metric-box" style="border-color: #ffd700;">
            <span style="color:#ffd700">FINAL PREDICTION (With CCF)</span><br>
            <span class="big-font">{predicted_fix:.4f}</span>
        </div>
        """, unsafe_allow_html=True)
         
    st.markdown("### Component Breakdown (in Pips)")
    
    chart_data = pd.DataFrame({
        'Component': ['Spot Closing Gap', 'Basket Impact', 'Counter-Cyclical Factor'],
        'Pips': [gap_pips, basket_pips, ccf_pips]
    })
    
    st.bar_chart(chart_data.set_index('Component'))
    
    if abs(predicted_fix - prev_close) > 0.0500:
        st.warning("⚠️ High Volatility Alert: Significant deviation between Close and Predicted Fix.")

