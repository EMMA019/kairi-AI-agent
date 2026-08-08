import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

class LeadLagPredictor:
    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.models = {} # dict of Ridge models per JP sector
        
    def fit(self, F_us: pd.DataFrame, Y_jp: pd.DataFrame):
        """
        F_us: Features (US factors at t-1)
        Y_jp: Target (JP sector returns at t)
        """
        self.models = {}
        for col in Y_jp.columns:
            model = Ridge(alpha=self.alpha)
            model.fit(F_us, Y_jp[col])
            self.models[col] = model
            
    def predict(self, F_us: pd.DataFrame) -> pd.DataFrame:
        """
        Predict JP sector returns for given US factors.
        """
        preds = {}
        for col, model in self.models.items():
            preds[col] = model.predict(F_us)
        return pd.DataFrame(preds, index=F_us.index)

def generate_allocations(predictions: pd.Series, n_top: int = 3) -> dict:
    """
    Generate Long/Short allocations based on predictions for the current day.
    """
    preds_sorted = predictions.sort_values(ascending=False)
    long_sectors = preds_sorted.head(n_top).index.tolist()
    short_sectors = preds_sorted.tail(n_top).index.tolist()
    
    allocations = {
        "Long": {sector: preds_sorted[sector] for sector in long_sectors},
        "Short": {sector: preds_sorted[sector] for sector in short_sectors},
        "Expected_Returns": predictions.to_dict()
    }
    return allocations
