import os
import webbrowser
import numpy as np
import plotly.graph_objects as go
from .models import TraceConfig

RAW_MARKER_SIZE  = 2
RAW_MARKER_ALPHA = 0.25

def create_3d_plot(
    airfoil_name: str,
    ncrit: float,
    X: np.ndarray,
    Y: np.ndarray,
    trace_configs: list[TraceConfig],
    raw_alpha: np.ndarray,
    raw_re: np.ndarray,
    show_scatter: bool,
    valid_count: int,
    output_dir: str = ".",
) -> str:
    """Plotly を使用して 3D グラフを作成し、HTML を保存する。"""
    raw_marker = dict(size=RAW_MARKER_SIZE, color=f'rgba(0, 0, 0, {RAW_MARKER_ALPHA})')

    fig = go.Figure()
    traces_per_config = 2 if show_scatter else 1

    for i, tc in enumerate(trace_configs):
        visible = (i == 0)
        fig.add_trace(go.Surface(
            z=tc.surf_z, x=X, y=Y, colorscale=tc.colorscale,
            name=f'{tc.label} (補間面)', opacity=0.85, visible=visible,
        ))
        if show_scatter:
            fig.add_trace(go.Scatter3d(
                x=raw_alpha, y=raw_re, z=tc.raw_z, mode='markers',
                marker=raw_marker,
                name=f'{tc.label} (生データ点)', visible=visible,
            ))

    buttons = []
    for i, tc in enumerate(trace_configs):
        vis = [False] * (len(trace_configs) * traces_per_config)
        vis[i * traces_per_config] = True
        if show_scatter:
            vis[i * traces_per_config + 1] = True
        buttons.append(dict(
            label=tc.label, method="update",
            args=[{"visible": vis}, {"scene.zaxis.title": tc.z_title}],
        ))

    scatter_note = "" if show_scatter else "  ※生データ点非表示"
    fig.update_layout(
        title=dict(
            text=(f'{airfoil_name} 3D Polar  (N-crit: {ncrit})<br>'
                  f'<sub>Thin-Plate Spline 補間 / {valid_count} 収束点{scatter_note}</sub>'),
            x=0.01, xanchor='left',
            y=0.97, yanchor='top',
            font=dict(size=14),
            pad=dict(t=8),
        ),
        scene=dict(
            xaxis_title='Alpha (deg)',
            yaxis_title='Reynolds Number',
            zaxis_title='Lift Coefficient (Cl)',
            xaxis=dict(nticks=10),
            yaxis=dict(nticks=10),
            zaxis=dict(nticks=10),
        ),
        updatemenus=[dict(
            type="buttons", direction="left", showactive=True,
            x=0.99, xanchor='right',
            y=0.97, yanchor='top',
            pad=dict(t=8, b=0),
            buttons=buttons,
        )],
        autosize=True,
        margin=dict(l=0, r=0, b=0, t=100),
    )

    output_html = os.path.join(output_dir, f'{airfoil_name}_polar_3d.html')
    fig.write_html(output_html, full_html=True, include_plotlyjs='cdn', config={'responsive': True})

    try:
        webbrowser.open('file://' + os.path.abspath(output_html))
    except Exception:
        pass

    return output_html
