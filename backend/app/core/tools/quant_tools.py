from app.core.quant.data_loader import get_aligned_lead_lag_returns, JP_SECTORS
from app.core.quant.subspace_pca import SubspaceRegularizedPCA, get_us_prior_matrix
from app.core.quant.lead_lag_predictor import LeadLagPredictor, generate_allocations
import json

from app.core.tools.registry import tool_registry

@tool_registry.register(name="analyze_sector_lead_lag", description="Analyzes US-Japan sector lead-lag using Subspace Regularized PCA to recommend Japanese sector Long/Short pairs for today.")
def analyze_sector_lead_lag() -> str:
    """
    Analyzes the US-Japan sector lead-lag relationship using Subspace Regularized PCA.
    Returns a JSON string containing the recommended Long/Short portfolio for today's JP market
    and the underlying US factor drivers.
    """
    try:
        # 1. Fetch Data (Lookback 252 days for training)
        X_us, Y_jp = get_aligned_lead_lag_returns(lookback_days=252)
        if X_us.empty or Y_jp.empty:
            return json.dumps({"error": "Insufficient data to run the quant model."})
            
        # 2. Extract US Factors (Subspace Regularized PCA)
        W_prior = get_us_prior_matrix(X_us.columns)
        pca = SubspaceRegularizedPCA(n_components=5, alpha=1.0)
        F_us = pca.fit_transform(X_us, W_prior)
        
        # 3. Train Lead-Lag Predictor & Predict Today
        # We predict Y_jp(t) using F_us(t-1)
        predictor = LeadLagPredictor(alpha=10.0) # Ridge regularization
        predictor.fit(F_us[:-1], Y_jp[1:]) # Train on shifted data
        
        # Predict for today using the latest US factor (from yesterday's US close)
        latest_us_factor = F_us.tail(1)
        todays_prediction = predictor.predict(latest_us_factor).iloc[0]
        
        # 4. Generate Allocations
        allocations = generate_allocations(todays_prediction, n_top=3)
        
        # Convert tickers to names
        longs = {JP_SECTORS.get(k, k): v for k, v in allocations["Long"].items()}
        shorts = {JP_SECTORS.get(k, k): v for k, v in allocations["Short"].items()}
        
        # Latest factor movements (to explain WHY)
        latest_factors = latest_us_factor.iloc[0].to_dict()
        factor_names = {
            "Factor_1": "Market (Overall Trend)",
            "Factor_2": "Cyclical vs Defensive",
            "Factor_3": "Tech/Growth vs Value",
            "Factor_4": "Interest Rate Sensitivity",
            "Factor_5": "FX (USD/JPY) Sensitivity"
        }
        explained_factors = {factor_names.get(k, k): v for k, v in latest_factors.items()}
        
        # Generate a Markdown Sector Map representation
        long_items = list(longs.items())
        short_items = list(shorts.items())
        
        map_md = "### 🗺️ Kairi's Sector Map (US Lead-Lag Prediction)\n\n"
        map_md += "| 🟩 **BUY (資金流入予測)** | 🟥 **SELL (資金流出予測)** |\n"
        map_md += "|:---|:---|\n"
        
        for i in range(max(len(long_items), len(short_items))):
            l_text = f"**{long_items[i][0]}**<br>+{long_items[i][1]:.3f}" if i < len(long_items) else ""
            s_text = f"**{short_items[i][0]}**<br>{short_items[i][1]:.3f}" if i < len(short_items) else ""
            map_md += f"| {l_text} | {s_text} |\n"

        result = {
            "Status": "Success",
            "Model": "Subspace Regularized PCA (Nakagawa et al. 2026)",
            "Date": Y_jp.index[-1].strftime("%Y-%m-%d"),
            "Recommended_Longs": longs,
            "Recommended_Shorts": shorts,
            "Latest_US_Drivers": explained_factors,
            "Markdown_Sector_Map": map_md
        }
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)})


