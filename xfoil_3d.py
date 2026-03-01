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
from pathlib import Path
from tqdm import tqdm
from scipy.interpolate import Rbf
import yaml
try:
    import questionary
    QUESTIONARY_AVAILABLE = True
except ImportError:
    QUESTIONARY_AVAILABLE = False



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


def load_config(config_path: str) -> dict:
    """YAMLファイルから設定を読み込む"""
    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    print(f"設定ファイルを読み込みました: {config_path}")
    return cfg


def save_config(config_path: str, cfg: dict) -> None:
    """設定をYAMLファイルに保存する"""
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"設定を保存しました: {config_path}")


def interactive_mode() -> dict:
    """
    引数が指定されていない場合に対話式でパラメータを入力するモード。
    questionary がない場合は通常の input() にフォールバックする。
    """
    print("\n=== XFOIL 3D Polar - インタラクティブモード ===")

    # Airfoils/ ディレクトリの .dat ファイルを列挙
    airfoil_dir = Path('Airfoils')
    dat_files = sorted(str(p) for p in airfoil_dir.glob('*.dat')) if airfoil_dir.exists() else []

    if QUESTIONARY_AVAILABLE:
        # --- questionary を使ったリッチなプロンプト ---
        if dat_files:
            choices = dat_files + ['[手動入力]']
            dat_choice = questionary.select(
                "翼型ファイルを選択してください:",
                choices=choices
            ).ask()
            if dat_choice == '[手動入力]':
                dat_file = questionary.text("翼型ファイルのパスを入力:").ask()
            else:
                dat_file = dat_choice
        else:
            dat_file = questionary.text("翼型ファイルのパスを入力:").ask()

        re_min   = float(questionary.text("レイノルズ数 最小値:",  default="100000").ask())
        re_max   = float(questionary.text("レイノルズ数 最大値:",  default="500000").ask())
        re_count = int  (questionary.text("レイノルズ数 分割数:",  default="5").ask())
        a_min    = float(questionary.text("迎角 最小 (deg):",       default="-10").ask())
        a_max    = float(questionary.text("迎角 最大 (deg):",       default="15").ask())
        a_step   = float(questionary.text("迎角 ステップ (deg):",   default="1").ask())
        ncrit    = float(questionary.text("N-crit 値:",             default="9.0").ask())
        xfoil_exe = questionary.text("XFOIL 実行ファイルパス:",      default="xfoil.exe").ask()
        open_browser = questionary.confirm("計算後にブラウザを自動で開きますか?", default=True).ask()
    else:
        # --- フォールバック: 標準 input() ---
        if dat_files:
            print("利用可能な翼型ファイル:")
            for i, f in enumerate(dat_files):
                print(f"  [{i}] {f}")
            idx = input("番号を選択 (手動入力は Enter): ").strip()
            dat_file = dat_files[int(idx)] if idx.isdigit() and int(idx) < len(dat_files) else input("ファイルパス: ").strip()
        else:
            dat_file = input("翼型ファイルのパスを入力: ").strip()
        re_min    = float(input("レイノルズ数 最小値 [100000]: ").strip() or "100000")
        re_max    = float(input("レイノルズ数 最大値 [500000]: ").strip() or "500000")
        re_count  = int  (input("レイノルズ数 分割数 [5]: ").strip() or "5")
        a_min     = float(input("迎角 最小 (deg) [-10]: ").strip() or "-10")
        a_max     = float(input("迎角 最大 (deg) [15]: ").strip() or "15")
        a_step    = float(input("迎角 ステップ (deg) [1]: ").strip() or "1")
        ncrit     = float(input("N-crit 値 [9.0]: ").strip() or "9.0")
        xfoil_exe = input("XFOIL 実行ファイルパス [xfoil.exe]: ").strip() or "xfoil.exe"
        open_browser = (input("計算後にブラウザを開きますか？ [Y/n]: ").strip().lower() != 'n')

    cfg = {
        'dat_file':    dat_file,
        're_range':    [re_min, re_max, re_count],
        'alpha_range': [a_min, a_max, a_step],
        'ncrit':       ncrit,
        'xfoil_exe':   xfoil_exe,
        'no_browser':  not open_browser,
    }

    # 設定の保存確認
    if QUESTIONARY_AVAILABLE:
        do_save = questionary.confirm("この設定を YAML ファイルに保存しますか?", default=True).ask()
        if do_save:
            fname = questionary.text("保存先ファイル名:", default="config.yaml").ask()
            save_config(fname, cfg)
    else:
        do_save = input("設定を YAML ファイルに保存しますか？ [Y/n]: ").strip().lower() != 'n'
        if do_save:
            fname = input("保存先ファイル名 [config.yaml]: ").strip() or "config.yaml"
            save_config(fname, cfg)

    print()
    return cfg


def main():
    parser = argparse.ArgumentParser(
        description="XFOIL 3D Polar Visualization Tool (Cl, Cd, Cm)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="引数を省略するとインタラクティブモードで起動します。\n例: python xfoil_3d.py --config config.yaml"
    )
    parser.add_argument('--dat_file',    type=str,   help="翼型 .dat ファイルのパス")
    parser.add_argument('--re_range',    type=float, nargs=3, metavar=('MIN','MAX','COUNT'), help="レイノルズ数: min max 分割数")
    parser.add_argument('--alpha_range', type=float, nargs=3, metavar=('MIN','MAX','STEP'),  help="迎角: min max step (deg)")
    parser.add_argument('--ncrit',       type=float, default=9.0, help="N-crit 値 (デフォルト: 9.0)")
    parser.add_argument('--xfoil_exe',   type=str,   default='xfoil.exe', help="XFOIL 実行ファイルのパス")
    parser.add_argument('--no_browser',  action='store_true', help="ブラウザの自動起動を無効化")
    parser.add_argument('--config',      type=str,   help="YAML 設定ファイルのパス")
    parser.add_argument('--save_config', type=str,   metavar='FILE', help="現在の設定を指定の YAML ファイルに保存して終了")

    args = parser.parse_args()

    # ── 設定の優先順位: --config > CLI引数 > インタラクティブモード ──
    if args.config:
        # YAML ファイルから設定を読み込む
        if not os.path.exists(args.config):
            print(f"Error: 設定ファイル '{args.config}' が見つかりません。")
            return
        cfg = load_config(args.config)
        # CLI 引数で個別オーバーライド可能
        if args.dat_file:    cfg['dat_file']    = args.dat_file
        if args.re_range:    cfg['re_range']    = list(args.re_range)
        if args.alpha_range: cfg['alpha_range'] = list(args.alpha_range)
        if args.ncrit != 9.0: cfg['ncrit']      = args.ncrit
        if args.no_browser:  cfg['no_browser']  = True
    elif args.dat_file and args.re_range and args.alpha_range:
        # 必須引数がすべて指定されている場合はそのまま使用
        cfg = {
            'dat_file':    args.dat_file,
            're_range':    list(args.re_range),
            'alpha_range': list(args.alpha_range),
            'ncrit':       args.ncrit,
            'xfoil_exe':   args.xfoil_exe,
            'no_browser':  args.no_browser,
        }
    else:
        # 必須引数が不足 → インタラクティブモード
        cfg = interactive_mode()

    # --save_config: 設定を保存して終了
    if args.save_config:
        save_config(args.save_config, cfg)
        return

    # cfg から各変数を取り出す
    dat_file_arg  = cfg.get('dat_file', '')
    re_min, re_max, re_count = cfg['re_range']
    re_count = int(re_count)
    alpha_min, alpha_max, alpha_step = cfg['alpha_range']
    ncrit_val   = cfg.get('ncrit', 9.0)
    xfoil_exe_arg = cfg.get('xfoil_exe', 'xfoil.exe')
    no_browser_val = cfg.get('no_browser', False)

    if not os.path.exists(dat_file_arg):
        print(f"Error: ファイル '{dat_file_arg}' が見つかりません。")
        return

    if not os.path.exists(xfoil_exe_arg):
        try:
            subprocess.run([xfoil_exe_arg], input="QUIT\n", text=True, capture_output=True, timeout=2)
        except FileNotFoundError:
            print(f"Error: XFOIL 実行ファイル '{xfoil_exe_arg}' が見つかりません。")
            return

    res = np.linspace(re_min, re_max, re_count)
    alphas = np.arange(alpha_min, alpha_max + alpha_step/2.0, alpha_step)
    
    num_processes = mp.cpu_count()
    print(f"Starting XFOIL calculations using {num_processes} processes...")
    print(f"Airfoil: {dat_file_arg}")
    print(f"Re range: {re_min} to {re_max} ({re_count} steps)")
    
    xfoil_exe_abs = os.path.abspath(xfoil_exe_arg) if os.path.exists(xfoil_exe_arg) else xfoil_exe_arg
    dat_file_abs = os.path.abspath(dat_file_arg)
    airfoil_name = os.path.splitext(os.path.basename(dat_file_arg))[0]
    
    clean_path = f"clean_{airfoil_name}_{uuid.uuid4().hex[:6]}.dat"
    clean_airfoil_dat(dat_file_abs, clean_path)
    
    tasks = [(os.path.abspath(clean_path), Re, alpha_min, alpha_max, alpha_step, ncrit_val, xfoil_exe_abs) for Re in res]
    
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
            text=f'{airfoil_name} 3D Polar (N-crit: {ncrit_val})<br><sub>Approximated via Thin-Plate Spline (RBF) over {valid_run_count} converged points</sub>',
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
    
    if not no_browser_val:
        try:
            html_path = 'file://' + os.path.abspath(output_html)
            webbrowser.open(html_path)
        except Exception:
            pass

if __name__ == '__main__':
    mp.freeze_support()
    main()
