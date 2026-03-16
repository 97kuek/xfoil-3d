import numpy as np
from scipy.interpolate import RBFInterpolator

def interpolate_rbf(
    x_norm: np.ndarray,
    y_norm: np.ndarray,
    z_values: np.ndarray,
    grid_x_norm: np.ndarray,
    grid_y_norm: np.ndarray,
) -> np.ndarray:
    """Thin-Plate Spline (RBF) によるサーフェス補間。"""
    points = np.column_stack([x_norm, y_norm])
    rbf    = RBFInterpolator(points, z_values, kernel='thin_plate_spline', smoothing=0.0)
    query  = np.column_stack([grid_x_norm.ravel(), grid_y_norm.ravel()])
    return rbf(query).reshape(grid_x_norm.shape)
