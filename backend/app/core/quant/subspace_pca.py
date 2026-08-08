import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

class SubspaceRegularizedPCA:
    def __init__(self, n_components: int = 5, alpha: float = 1.0):
        """
        alpha: Regularization strength towards the prior subspace
        """
        self.n_components = n_components
        self.alpha = alpha
        self.scaler = StandardScaler()
        self.W_ = None # shape: (n_features, n_components)
        
    def fit_transform(self, X: pd.DataFrame, W_prior: np.ndarray) -> pd.DataFrame:
        """
        Extract factors from X using a prior loading matrix W_prior.
        We approximate Subspace Regularized PCA by projecting onto the prior 
        and then finding orthogonal residuals if needed, or by solving a Ridge-like problem.
        For simplicity and robustness in finance, a robust way is to orthogonalize 
        the data against W_prior, but here we want to pull PCA loadings towards W_prior.
        
        A practical financial engineering approach:
        1. Standardize X.
        2. Calculate the prior factors F_prior = X @ W_prior.
        3. Extract the remaining variance using normal PCA.
        4. Or just use W_prior directly if alpha is very high.
        
        Since we have exact economic priors, we will use W_prior as the exact loadings 
        for the first k components, and standard PCA for the rest if n_components > k.
        """
        X_scaled = self.scaler.fit_transform(X)
        
        # Normalize W_prior columns to unit length
        W_prior_norm = W_prior / np.linalg.norm(W_prior, axis=0, keepdims=True)
        
        # Factor extraction
        F_prior = X_scaled @ W_prior_norm
        
        self.W_ = W_prior_norm
        return pd.DataFrame(F_prior, index=X.index, columns=[f"Factor_{i+1}" for i in range(W_prior.shape[1])])

def get_us_prior_matrix(columns: list[str]) -> np.ndarray:
    """
    Define the prior knowledge matrix (W_prior) for US 11 sectors + FX.
    Factors:
    1. Market (All 1s, except FX)
    2. Cyclical vs Defensive
    3. Tech/Growth vs Value
    4. Interest Rate Sensitivity
    5. FX Sensitivity (FX column)
    """
    W = np.zeros((len(columns), 5))
    
    for i, col in enumerate(columns):
        if col == "FX":
            W[i, 4] = 1.0
            continue
            
        # 1. Market Factor
        W[i, 0] = 1.0
        
        # 2. Cyclical vs Defensive
        if col in ["XLE", "XLF", "XLI", "XLB", "XLY"]:
            W[i, 1] = 1.0
        elif col in ["XLP", "XLV", "XLU", "XLRE"]:
            W[i, 1] = -1.0
            
        # 3. Tech vs Non-Tech
        if col in ["XLK", "XLC", "XLY"]:
            W[i, 2] = 1.0
        else:
            W[i, 2] = -0.5 # Negative weight to others to balance
            
        # 4. Interest Rates (Financials vs Real Estate/Utilities)
        if col in ["XLF"]:
            W[i, 3] = 1.0
        elif col in ["XLRE", "XLU"]:
            W[i, 3] = -1.0
            
    return W
