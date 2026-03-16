from typing import NamedTuple
import numpy as np

class TraceConfig(NamedTuple):
    """3D グラフの1指標分の設定。"""
    surf_z:     np.ndarray
    raw_z:      np.ndarray
    colorscale: str
    label:      str
    z_title:    str
