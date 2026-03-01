import argparse
import multiprocessing as mp
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import os
import webbrowser
import subprocess
import tempfile
import uuid
from tqdm import tqdm
from scipy.interpolate import Rbf


def calculate_polar(args):
    """
    Worker function for multiprocessing.
    Calculates polar for a given Reynolds number using xfoil.exe in subprocess.
    """
    dat_file, Re, alpha_min, alpha_max, alpha_step, ncrit, xfoil_exe = args
    
    uid = uuid.uuid4().hex[:8]
    polar_file = f"polar_{Re}_{uid}.txt"
    dump_file = f"dump_{Re}_{uid}.txt"
    
    commands = f"""
PLOP
G F

LOAD {dat_file}
PANE
OPER
ITER 200
Visc {Re}
VPAR
N {ncrit}

PACC
{polar_file}
{dump_file}
ASEQ {alpha_min} {alpha_max} {alpha_step}
PACC

QUIT
"""
    
    try:
        process = subprocess.run(
            [xfoil_exe],
            input=commands,
            text=True,
            capture_output=True,
            timeout=180
        )
    except Exception as e:
        return None

    alphas = np.arange(alpha_min, alpha_max + alpha_step/2.0, alpha_step)
    
    # Initialize arrays for Cl, Cd, Cm
    cl_results = np.full_like(alphas, np.nan)
    cd_results = np.full_like(alphas, np.nan)
    cm_results = np.full_like(alphas, np.nan)
    
    if os.path.exists(polar_file):
        try:
            with open(polar_file, 'r') as f:
                lines = f.readlines()
                
            data_started = False
            for line in lines:
                if '------' in line:
                    data_started = True
                    continue
                if data_started:
                    parts = line.split()
                    if len(parts) >= 5:
                        try:
                            a = float(parts[0])
                            cl = float(parts[1])
                            cd = float(parts[2])
                            # parts[3] is CDp (pressure drag), parts[4] is CM
                            cm = float(parts[4])
                            
                            idx = np.abs(alphas - a).argmin()
                            if np.abs(alphas[idx] - a) < 1e-3:
                                cl_results[idx] = cl
                                cd_results[idx] = cd
                                cm_results[idx] = cm
                        except ValueError:
                            pass
        except Exception:
            pass
            
        try:
            os.remove(polar_file)
            if os.path.exists(dump_file):
                os.remove(dump_file)
        except:
            pass
            
    return {'Re': Re, 'alphas': alphas, 'cls': cl_results, 'cds': cd_results, 'cms': cm_results}

def clean_airfoil_dat(in_path, out_path):
    try:
        with open(in_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        with open(out_path, 'w', encoding='utf-8') as f:
            for i, line in enumerate(lines):
                line = line.replace('\t', ' ').strip()
                if not line: continue
                if i == 0:
                    f.write(line + '\n')
                else:
                    parts = line.split()
                    if len(parts) >= 2:
                        f.write(f" {parts[0]}  {parts[1]}\n")
    except Exception as e:
        print(f"Warning: Failed to clean dat file: {e}")

def main():
    parser = argparse.ArgumentParser(description="XFOIL 3D Polar Visualization Tool (Cl, Cd, Cm)")
    parser.add_argument('--dat_file', type=str, required=True, help="Path to the airfoil .dat file")
    parser.add_argument('--re_range', type=float, nargs=3, metavar=('MIN', 'MAX', 'COUNT'), required=True, help="Reynolds number range: min max count")
    parser.add_argument('--alpha_range', type=float, nargs=3, metavar=('MIN', 'MAX', 'STEP'), required=True, help="Alpha range: min max step")
    parser.add_argument('--ncrit', type=float, default=9.0, help="N-crit value for XFOIL (default: 9.0)")
    parser.add_argument('--xfoil_exe', type=str, default='xfoil.exe', help="Path to XFOIL executable")
    parser.add_argument('--no_browser', action='store_true', help="Disable automatic browser opening")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.dat_file):
        print(f"Error: File '{args.dat_file}' not found.")
        return
        
    if not os.path.exists(args.xfoil_exe):
        try:
            subprocess.run([args.xfoil_exe], input="QUIT\n", text=True, capture_output=True, timeout=2)
        except FileNotFoundError:
             print(f"Error: XFOIL executable '{args.xfoil_exe}' not found.")
             return
             
    re_min, re_max, re_count = args.re_range
    re_count = int(re_count)
    res = np.linspace(re_min, re_max, re_count)
    
    alpha_min, alpha_max, alpha_step = args.alpha_range
    alphas = np.arange(alpha_min, alpha_max + alpha_step/2.0, alpha_step)
    
    num_processes = mp.cpu_count()
    print(f"Starting XFOIL calculations using {num_processes} processes...")
    print(f"Airfoil: {args.dat_file}")
    print(f"Re range: {re_min} to {re_max} ({re_count} steps)")
    
    xfoil_exe_abs = os.path.abspath(args.xfoil_exe) if os.path.exists(args.xfoil_exe) else args.xfoil_exe
    dat_file_abs = os.path.abspath(args.dat_file)
    airfoil_name = os.path.splitext(os.path.basename(args.dat_file))[0]
    
    clean_path = f"clean_{airfoil_name}_{uuid.uuid4().hex[:6]}.dat"
    clean_airfoil_dat(dat_file_abs, clean_path)
    
    tasks = [(os.path.abspath(clean_path), Re, alpha_min, alpha_max, alpha_step, args.ncrit, xfoil_exe_abs) for Re in res]
    
    results = []
    # Using tqdm for progress bar
    with mp.Pool(num_processes) as pool:
        for r in tqdm(pool.imap_unordered(calculate_polar, tasks), total=len(tasks), desc="Simulating"):
            if r is not None:
                results.append(r)
                
    if not results:
        print("Error: No valid results were calculated.")
        return
        
    # Prepare DataFrames & 3D matrices
    X, Y = np.meshgrid(alphas, res)
    Z_cl = np.full_like(X, np.nan)
    Z_cd = np.full_like(X, np.nan)
    Z_cm = np.full_like(X, np.nan)
    
    csv_data = []
    
    valid_run_count = 0
    for r in results:
        Re = r['Re']
        re_idx = np.abs(res - Re).argmin()
        
        cls, cds, cms = r['cls'], r['cds'], r['cms']
        
        for j, alpha in enumerate(alphas):
            cl, cd, cm = cls[j], cds[j], cms[j]
            Z_cl[re_idx, j] = cl
            Z_cd[re_idx, j] = cd
            Z_cm[re_idx, j] = cm
            
            if not np.isnan(cl):
                valid_run_count += 1
                csv_data.append({
                    "Airfoil": airfoil_name,
                    "Re": Re,
                    "Alpha": alpha,
                    "Cl": cl,
                    "Cd": cd,
                    "Cm": cm
                })
                
    print(f"\nCalculations completed. Rendered {valid_run_count} converged data points out of {len(res)*len(alphas)}.")
    
    if not csv_data:
        print("Error: All XFOIL runs failed to converge.")
        return

    df = pd.DataFrame(csv_data)
    csv_file = f"{airfoil_name}_polar_raw.csv"
    df.to_csv(csv_file, index=False)
    print(f"Saved raw numerical data to {csv_file}")
    
    print("Interpolating missing data points with high-accuracy RBF (Thin-plate spline)...")
    
    raw_alpha = df['Alpha'].values
    raw_re = df['Re'].values
    
    # RBF is sensitive to scale differences (Re is O(1e5), Alpha is O(10)).
    # We must normalize the coordinates to [0, 1] for accurate multidimensional distance calculation.
    a_min, a_max = raw_alpha.min(), raw_alpha.max()
    r_min, r_max = raw_re.min(), raw_re.max()
    d_a = (a_max - a_min) if (a_max > a_min) else 1.0
    d_r = (r_max - r_min) if (r_max > r_min) else 1.0
    
    raw_a_norm = (raw_alpha - a_min) / d_a
    raw_r_norm = (raw_re - r_min) / d_r
    X_norm = (X - a_min) / d_a
    Y_norm = (Y - r_min) / d_r
    
    def interpolate_surface_rbf(x_norm, y_norm, z_values, grid_X_norm, grid_Y_norm):
        # Thin-plate spline minimizes bending energy, producing physically smooth surfaces 
        # that exactly pass through the provided deterministic datapoints (smooth=0.0).
        rbf = Rbf(x_norm, y_norm, z_values, function='thin_plate', smooth=0.0)
        return rbf(grid_X_norm, grid_Y_norm)

    Z_cl_interp = interpolate_surface_rbf(raw_a_norm, raw_r_norm, df['Cl'].values, X_norm, Y_norm)
    Z_cd_interp = interpolate_surface_rbf(raw_a_norm, raw_r_norm, df['Cd'].values, X_norm, Y_norm)
    Z_cm_interp = interpolate_surface_rbf(raw_a_norm, raw_r_norm, df['Cm'].values, X_norm, Y_norm)

    with np.errstate(divide='ignore', invalid='ignore'):
        Z_ld_interp = np.where(Z_cd_interp != 0, Z_cl_interp / Z_cd_interp, np.nan)
        values_ld = np.where(df['Cd'].values != 0, df['Cl'].values / df['Cd'].values, np.nan)

    # Export interpolated grid data
    interp_csv_data = []
    for i in range(len(res)):
        for j in range(len(alphas)):
            interp_csv_data.append({
                "Airfoil": airfoil_name,
                "Re": res[i],
                "Alpha": alphas[j],
                "Cl": Z_cl_interp[i, j],
                "Cd": Z_cd_interp[i, j],
                "Cm": Z_cm_interp[i, j]
            })
    df_interp = pd.DataFrame(interp_csv_data)
    interp_csv_file = f"{airfoil_name}_polar_interp.csv"
    df_interp.to_csv(interp_csv_file, index=False)
    print(f"Saved interpolated grid data to {interp_csv_file}")
    
    # Create 3D plot
    fig = go.Figure()

    raw_x = df['Alpha'].values
    raw_y = df['Re'].values

    # 0, 1: Cl
    fig.add_trace(go.Surface(z=Z_cl_interp, x=X, y=Y, colorscale='Viridis', name='Cl (Interpolated)', opacity=0.85, visible=True))
    fig.add_trace(go.Scatter3d(x=raw_alpha, y=raw_re, z=df['Cl'].values, mode='markers', marker=dict(size=2, color='black'), name='Cl (Raw Points)', visible=True))
    
    # 2, 3: Cd
    fig.add_trace(go.Surface(z=Z_cd_interp, x=X, y=Y, colorscale='Cividis', name='Cd (Interpolated)', opacity=0.85, visible=False))
    fig.add_trace(go.Scatter3d(x=raw_alpha, y=raw_re, z=df['Cd'].values, mode='markers', marker=dict(size=2, color='black'), name='Cd (Raw Points)', visible=False))
    
    # 4, 5: Cm
    fig.add_trace(go.Surface(z=Z_cm_interp, x=X, y=Y, colorscale='Plasma', name='Cm (Interpolated)', opacity=0.85, visible=False))
    fig.add_trace(go.Scatter3d(x=raw_alpha, y=raw_re, z=df['Cm'].values, mode='markers', marker=dict(size=2, color='black'), name='Cm (Raw Points)', visible=False))
    
    # 6, 7: L/D
    fig.add_trace(go.Surface(z=Z_ld_interp, x=X, y=Y, colorscale='Inferno', name='Cl/Cd (Interpolated)', opacity=0.85, visible=False))
    fig.add_trace(go.Scatter3d(x=raw_alpha, y=raw_re, z=values_ld, mode='markers', marker=dict(size=2, color='black'), name='Cl/Cd (Raw Points)', visible=False))

    fig.update_layout(
        title=dict(
            text=f'{airfoil_name} 3D Polar (N-crit: {args.ncrit})<br><sub>Approximated via Thin-Plate Spline (RBF) over {valid_run_count} converged points</sub>',
            y=0.97,
            x=0.02,
            xanchor='left',
            yanchor='top'
        ),
        scene=dict(
            xaxis_title='Alpha (deg)',
            yaxis_title='Reynolds Number',
            zaxis_title='Coefficient',
            xaxis=dict(nticks=10),
            yaxis=dict(nticks=10),
            zaxis=dict(nticks=10)
        ),
        updatemenus=[
            dict(
                type="buttons",
                direction="right",
                showactive=True,
                x=0.02,
                y=1.0,
                xanchor='left',
                yanchor='bottom',
                buttons=list([
                    dict(label="Cl (Lift)",
                         method="update",
                         args=[{"visible": [True, True, False, False, False, False, False, False]},
                               {"scene.zaxis.title": "Lift Coefficient (Cl)"}]),
                    dict(label="Cd (Drag)",
                         method="update",
                         args=[{"visible": [False, False, True, True, False, False, False, False]},
                               {"scene.zaxis.title": "Drag Coefficient (Cd)"}]),
                    dict(label="Cm (Moment)",
                         method="update",
                         args=[{"visible": [False, False, False, False, True, True, False, False]},
                               {"scene.zaxis.title": "Moment Coefficient (Cm)"}]),
                    dict(label="Cl/Cd (Efficiency)",
                         method="update",
                         args=[{"visible": [False, False, False, False, False, False, True, True]},
                               {"scene.zaxis.title": "Lift-to-Drag Ratio (Cl/Cd)"}]),
                ]),
            )
        ],
        autosize=True,
        margin=dict(l=0, r=0, b=0, t=60)
    )
    
    output_html = f'{airfoil_name}_polar_3d.html'
    fig.write_html(
        output_html,
        full_html=True,
        include_plotlyjs='cdn',
        config={'responsive': True}
    )
    print(f"Saved interactive 3D plot to {output_html}")
    
    if os.path.exists(clean_path):
        os.remove(clean_path)
    
    if not args.no_browser:
        try:
            html_path = 'file://' + os.path.abspath(output_html)
            webbrowser.open(html_path)
        except Exception:
            pass

if __name__ == '__main__':
    mp.freeze_support()
    main()
