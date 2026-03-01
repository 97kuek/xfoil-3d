"""
xfoil_3d.py - XFOIL 3D極曲線 可視化ツール

XFOILを使って翼型のCl・Cd・Cm・Cl/Cdを複数レイノルズ数で並列計算し、
Thin-Plate Spline (RBF) 補間で3D極曲線サーフェスをHTML形式で出力する。
"""

import argparse
import multiprocessing as mp
import os
import subprocess
import uuid
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yaml
from scipy.interpolate import Rbf
from tqdm import tqdm

try:
    import questionary
    QUESTIONARY_AVAILABLE = True
except ImportError:
    QUESTIONARY_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# XFOIL 実行・解析
# ─────────────────────────────────────────────────────────────

def calculate_polar(args: tuple) -> dict | None:
    """
    マルチプロセス用ワーカー関数。
    指定されたレイノルズ数に対して XFOIL を実行し、
    Cl・Cd・Cm を alpha ごとに返す。
    """
    dat_file, Re, alpha_min, alpha_max, alpha_step, ncrit, xfoil_exe = args

    uid        = uuid.uuid4().hex[:8]
    polar_file = f"polar_{Re}_{uid}.txt"
    dump_file  = f"dump_{Re}_{uid}.txt"

    commands = (
        f"PLOP\nG F\n\n"
        f"LOAD {dat_file}\nPANE\nOPER\nITER 200\n"
        f"Visc {Re}\nVPAR\nN {ncrit}\n\n"
        f"PACC\n{polar_file}\n{dump_file}\n"
        f"ASEQ {alpha_min} {alpha_max} {alpha_step}\n"
        f"PACC\n\nQUIT\n"
    )

    try:
        subprocess.run(
            [xfoil_exe],
            input=commands,
            text=True,
            capture_output=True,
            timeout=180,
        )
    except Exception:
        return None

    alphas     = np.arange(alpha_min, alpha_max + alpha_step / 2.0, alpha_step)
    cl_results = np.full_like(alphas, np.nan)
    cd_results = np.full_like(alphas, np.nan)
    cm_results = np.full_like(alphas, np.nan)

    if os.path.exists(polar_file):
        try:
            with open(polar_file, encoding='utf-8') as f:
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
                            a  = float(parts[0])
                            cl = float(parts[1])
                            cd = float(parts[2])
                            cm = float(parts[4])  # parts[3] は CDp（圧力抗力）
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
        except OSError:
            pass

    return {
        'Re':   Re,
        'alphas': alphas,
        'cls':  cl_results,
        'cds':  cd_results,
        'cms':  cm_results,
    }


def clean_airfoil_dat(in_path: str, out_path: str) -> None:
    """
    XFOIL 用に .dat ファイルを正規化する。
    タブを空白に置換し、座標行を「 x  y」形式に統一する。
    """
    try:
        with open(in_path, encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        with open(out_path, 'w', encoding='utf-8') as f:
            for i, line in enumerate(lines):
                line = line.replace('\t', ' ').strip()
                if not line:
                    continue
                if i == 0:
                    f.write(line + '\n')
                else:
                    parts = line.split()
                    if len(parts) >= 2:
                        f.write(f" {parts[0]}  {parts[1]}\n")
    except Exception as e:
        print(f"警告: .dat ファイルの正規化に失敗しました: {e}")


# ─────────────────────────────────────────────────────────────
# RBF 補間（Thin-Plate Spline）
# ─────────────────────────────────────────────────────────────

def interpolate_rbf(
    x_norm: np.ndarray,
    y_norm: np.ndarray,
    z_values: np.ndarray,
    grid_x_norm: np.ndarray,
    grid_y_norm: np.ndarray,
) -> np.ndarray:
    """
    Thin-Plate Spline (RBF) によるサーフェス補間。

    アルゴリズム:
        薄板スプライン（Thin-Plate Spline）は2次元の曲げエネルギー

            E = ∫∫ [(∂²f/∂x²)² + 2(∂²f/∂x∂y)² + (∂²f/∂y²)²] dx dy

        を最小化する補間関数 f(x, y) を求める。
        基底関数は φ(r) = r² log(r)（r はユークリッド距離）。
        smooth=0.0 により、全データ点を厳密に通過する補間（スムージングなし）。

    スケール正規化について:
        Re は O(10⁵)、alpha は O(10) と桁が大きく異なる。
        ユークリッド距離の計算が Re 方向で支配的になるのを防ぐため、
        両軸を [0, 1] に正規化してから補間する。
    """
    rbf = Rbf(x_norm, y_norm, z_values, function='thin_plate', smooth=0.0)
    return rbf(grid_x_norm, grid_y_norm)


# ─────────────────────────────────────────────────────────────
# 設定ファイル (YAML)
# ─────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    """YAML ファイルから設定を読み込む。"""
    with open(config_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    print(f"設定ファイルを読み込みました: {config_path}")
    return cfg


def save_config(config_path: str, cfg: dict) -> None:
    """設定を YAML ファイルに保存する。"""
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"設定を保存しました: {config_path}")


# ─────────────────────────────────────────────────────────────
# インタラクティブモード
# ─────────────────────────────────────────────────────────────

def interactive_mode() -> dict:
    """
    引数が不足している場合に対話式でパラメータを入力するモード。
    questionary がインストールされていない場合は標準 input() にフォールバックする。
    """
    print("\n=== XFOIL 3D Polar - インタラクティブモード ===")

    airfoil_dir = Path('Airfoils')
    dat_files   = sorted(str(p) for p in airfoil_dir.glob('*.dat')) if airfoil_dir.exists() else []

    if QUESTIONARY_AVAILABLE:
        if dat_files:
            choices    = dat_files + ['[手動入力]']
            dat_choice = questionary.select("翼型ファイルを選択してください:", choices=choices).ask()
            dat_file   = questionary.text("翼型ファイルのパスを入力:").ask() if dat_choice == '[手動入力]' else dat_choice
        else:
            dat_file = questionary.text("翼型ファイルのパスを入力:").ask()

        re_min       = float(questionary.text("レイノルズ数 最小値:",   default="100000").ask())
        re_max       = float(questionary.text("レイノルズ数 最大値:",   default="500000").ask())
        re_count     = int  (questionary.text("レイノルズ数 分割数:",   default="5").ask())
        a_min        = float(questionary.text("迎角 最小 (deg):",       default="-10").ask())
        a_max        = float(questionary.text("迎角 最大 (deg):",       default="15").ask())
        a_step       = float(questionary.text("迎角 ステップ (deg):",   default="1").ask())
        ncrit        = float(questionary.text("N-crit 値:",             default="9.0").ask())
        xfoil_exe    = questionary.text(      "XFOIL 実行ファイルパス:", default="xfoil.exe").ask()
        open_browser = questionary.confirm("計算後にブラウザを自動で開きますか?", default=True).ask()
    else:
        if dat_files:
            print("利用可能な翼型ファイル:")
            for i, f in enumerate(dat_files):
                print(f"  [{i}] {f}")
            idx      = input("番号を選択 (手動入力は Enter): ").strip()
            dat_file = dat_files[int(idx)] if idx.isdigit() and int(idx) < len(dat_files) else input("ファイルパス: ").strip()
        else:
            dat_file = input("翼型ファイルのパスを入力: ").strip()

        re_min       = float(input("レイノルズ数 最小値 [100000]: ").strip() or "100000")
        re_max       = float(input("レイノルズ数 最大値 [500000]: ").strip() or "500000")
        re_count     = int  (input("レイノルズ数 分割数 [5]: "     ).strip() or "5")
        a_min        = float(input("迎角 最小 (deg) [-10]: "       ).strip() or "-10")
        a_max        = float(input("迎角 最大 (deg) [15]: "        ).strip() or "15")
        a_step       = float(input("迎角 ステップ (deg) [1]: "     ).strip() or "1")
        ncrit        = float(input("N-crit 値 [9.0]: "             ).strip() or "9.0")
        xfoil_exe    = input("XFOIL 実行ファイルパス [xfoil.exe]: ").strip() or "xfoil.exe"
        open_browser = (input("計算後にブラウザを開きますか？ [Y/n]: ").strip().lower() != 'n')

    cfg = {
        'dat_file':    dat_file,
        're_range':    [re_min, re_max, re_count],
        'alpha_range': [a_min, a_max, a_step],
        'ncrit':       ncrit,
        'xfoil_exe':   xfoil_exe,
        'no_browser':  not open_browser,
    }

    if QUESTIONARY_AVAILABLE:
        if questionary.confirm("この設定を YAML ファイルに保存しますか?", default=True).ask():
            fname = questionary.text("保存先ファイル名:", default="config.yaml").ask()
            save_config(fname, cfg)
    else:
        if input("設定を YAML ファイルに保存しますか？ [Y/n]: ").strip().lower() != 'n':
            fname = input("保存先ファイル名 [config.yaml]: ").strip() or "config.yaml"
            save_config(fname, cfg)

    print()
    return cfg


# ─────────────────────────────────────────────────────────────
# エントリポイント
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="XFOIL 3D Polar Visualization Tool (Cl, Cd, Cm)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="引数を省略するとインタラクティブモードで起動します。\n例: python xfoil_3d.py --config config.yaml",
    )
    parser.add_argument('--dat_file',    type=str,                                              help="翼型 .dat ファイルのパス")
    parser.add_argument('--re_range',    type=float, nargs=3, metavar=('MIN', 'MAX', 'COUNT'), help="レイノルズ数: min max 分割数")
    parser.add_argument('--alpha_range', type=float, nargs=3, metavar=('MIN', 'MAX', 'STEP'),  help="迎角: min max step (deg)")
    parser.add_argument('--ncrit',       type=float, default=9.0,                               help="N-crit 値 (デフォルト: 9.0)")
    parser.add_argument('--xfoil_exe',   type=str,   default='xfoil.exe',                      help="XFOIL 実行ファイルのパス")
    parser.add_argument('--no_browser',  action='store_true',                                   help="ブラウザの自動起動を無効化")
    parser.add_argument('--config',      type=str,                                              help="YAML 設定ファイルのパス")
    parser.add_argument('--save_config', type=str,   metavar='FILE',                            help="現在の設定を指定 YAML ファイルに保存して終了")
    args = parser.parse_args()

    # ── 設定の優先順位: --config > CLI引数 > インタラクティブ ──
    if args.config:
        if not os.path.exists(args.config):
            print(f"エラー: 設定ファイル '{args.config}' が見つかりません。")
            return
        cfg = load_config(args.config)
        # CLI 引数で個別オーバーライド可能
        if args.dat_file:     cfg['dat_file']    = args.dat_file
        if args.re_range:     cfg['re_range']    = list(args.re_range)
        if args.alpha_range:  cfg['alpha_range'] = list(args.alpha_range)
        if args.ncrit != 9.0: cfg['ncrit']       = args.ncrit
        if args.no_browser:   cfg['no_browser']  = True
    elif args.dat_file and args.re_range and args.alpha_range:
        cfg = {
            'dat_file':    args.dat_file,
            're_range':    list(args.re_range),
            'alpha_range': list(args.alpha_range),
            'ncrit':       args.ncrit,
            'xfoil_exe':   args.xfoil_exe,
            'no_browser':  args.no_browser,
        }
    else:
        cfg = interactive_mode()

    if args.save_config:
        save_config(args.save_config, cfg)
        return

    # ── cfg から変数を取り出す ──
    dat_file   = cfg.get('dat_file', '')
    re_min, re_max, re_count = cfg['re_range']
    re_count   = int(re_count)
    alpha_min, alpha_max, alpha_step = cfg['alpha_range']
    ncrit      = cfg.get('ncrit', 9.0)
    xfoil_exe  = cfg.get('xfoil_exe', 'xfoil.exe')
    no_browser = cfg.get('no_browser', False)

    # ── バリデーション ──
    if not os.path.exists(dat_file):
        print(f"エラー: ファイル '{dat_file}' が見つかりません。")
        return
    if not os.path.exists(xfoil_exe):
        try:
            subprocess.run([xfoil_exe], input="QUIT\n", text=True, capture_output=True, timeout=2)
        except FileNotFoundError:
            print(f"エラー: XFOIL 実行ファイル '{xfoil_exe}' が見つかりません。")
            return

    res    = np.linspace(re_min, re_max, re_count)
    alphas = np.arange(alpha_min, alpha_max + alpha_step / 2.0, alpha_step)

    airfoil_name  = os.path.splitext(os.path.basename(dat_file))[0]
    dat_file_abs  = os.path.abspath(dat_file)
    xfoil_exe_abs = os.path.abspath(xfoil_exe) if os.path.exists(xfoil_exe) else xfoil_exe

    print(f"\n翼型: {airfoil_name}")
    print(f"Re 範囲: {re_min:.0f} ～ {re_max:.0f}  ({re_count} 分割)")
    print(f"迎角: {alpha_min}° ～ {alpha_max}°  (ステップ {alpha_step}°)")
    print(f"N-crit: {ncrit} │ プロセス数: {mp.cpu_count()}")
    print()

    # ── .dat ファイルの正規化 ──
    clean_path = f"clean_{airfoil_name}_{uuid.uuid4().hex[:6]}.dat"
    clean_airfoil_dat(dat_file_abs, clean_path)

    # ── XFOIL 並列実行 ──
    tasks = [
        (os.path.abspath(clean_path), Re, alpha_min, alpha_max, alpha_step, ncrit, xfoil_exe_abs)
        for Re in res
    ]
    results = []
    with mp.Pool(mp.cpu_count()) as pool:
        for r in tqdm(pool.imap_unordered(calculate_polar, tasks), total=len(tasks), desc="計算中"):
            if r is not None:
                results.append(r)

    if os.path.exists(clean_path):
        os.remove(clean_path)

    if not results:
        print("エラー: 有効な計算結果がありません。")
        return

    # ── 結果を DataFrame に集約 ──
    rows = []
    for r in results:
        Re_val = r['Re']
        for j, alpha in enumerate(alphas):
            cl, cd, cm = r['cls'][j], r['cds'][j], r['cms'][j]
            if not np.isnan(cl):
                rows.append({'Airfoil': airfoil_name, 'Re': Re_val, 'Alpha': alpha,
                             'Cl': cl, 'Cd': cd, 'Cm': cm})

    if not rows:
        print("エラー: すべての XFOIL 実行が収束しませんでした。")
        return

    df          = pd.DataFrame(rows)
    valid_count = len(df)
    total_count = re_count * len(alphas)
    print(f"\n計算完了: {valid_count} / {total_count} 点が収束")

    csv_raw = f"{airfoil_name}_polar_raw.csv"
    df.to_csv(csv_raw, index=False)
    print(f"生データを保存: {csv_raw}")

    # ── RBF 補間（Thin-Plate Spline） ──
    print("RBF（薄板スプライン）補間中...")

    X, Y      = np.meshgrid(alphas, res)
    raw_alpha = df['Alpha'].values
    raw_re    = df['Re'].values

    # スケール正規化: alpha と Re の桁差を吸収する
    a_lo, a_hi = raw_alpha.min(), raw_alpha.max()
    r_lo, r_hi = raw_re.min(),    raw_re.max()
    d_a = (a_hi - a_lo) or 1.0
    d_r = (r_hi - r_lo) or 1.0

    ra_norm = (raw_alpha - a_lo) / d_a
    rr_norm = (raw_re    - r_lo) / d_r
    gx_norm = (X         - a_lo) / d_a
    gy_norm = (Y         - r_lo) / d_r

    Z_cl = interpolate_rbf(ra_norm, rr_norm, df['Cl'].values, gx_norm, gy_norm)
    Z_cd = interpolate_rbf(ra_norm, rr_norm, df['Cd'].values, gx_norm, gy_norm)
    Z_cm = interpolate_rbf(ra_norm, rr_norm, df['Cm'].values, gx_norm, gy_norm)

    with np.errstate(divide='ignore', invalid='ignore'):
        Z_ld        = np.where(Z_cd != 0, Z_cl / Z_cd, np.nan)
        raw_ld_vals = np.where(df['Cd'].values != 0, df['Cl'].values / df['Cd'].values, np.nan)

    # 補間グリッドを CSV に保存（vectorized）
    df_interp = pd.DataFrame({
        'Airfoil': airfoil_name,
        'Re':      Y.ravel(),
        'Alpha':   X.ravel(),
        'Cl':      Z_cl.ravel(),
        'Cd':      Z_cd.ravel(),
        'Cm':      Z_cm.ravel(),
    })
    csv_interp = f"{airfoil_name}_polar_interp.csv"
    df_interp.to_csv(csv_interp, index=False)
    print(f"補間グリッドを保存: {csv_interp}")

    # ── 3D プロット作成 ──
    # (surf_z, raw_z, colorscale, ボタンラベル, Z軸タイトル)
    TRACE_CONFIGS = [
        (Z_cl,      df['Cl'].values, 'Viridis', 'Cl (Lift)',         'Lift Coefficient (Cl)'),
        (Z_cd,      df['Cd'].values, 'Cividis', 'Cd (Drag)',         'Drag Coefficient (Cd)'),
        (Z_cm,      df['Cm'].values, 'Plasma',  'Cm (Moment)',       'Moment Coefficient (Cm)'),
        (Z_ld,      raw_ld_vals,     'Inferno', 'Cl/Cd (Efficiency)','Lift-to-Drag Ratio (Cl/Cd)'),
    ]

    fig = go.Figure()
    for i, (surf_z, raw_z, cscale, label, _) in enumerate(TRACE_CONFIGS):
        visible = (i == 0)
        fig.add_trace(go.Surface(
            z=surf_z, x=X, y=Y, colorscale=cscale,
            name=f'{label} (補間面)', opacity=0.85, visible=visible,
        ))
        fig.add_trace(go.Scatter3d(
            x=raw_alpha, y=raw_re, z=raw_z, mode='markers',
            marker=dict(size=2, color='black'),
            name=f'{label} (生データ点)', visible=visible,
        ))

    # 表示切り替えボタン（各指標につきトレース2本）
    buttons = []
    for i, (_, _, _, label, z_title) in enumerate(TRACE_CONFIGS):
        vis = [False] * (len(TRACE_CONFIGS) * 2)
        vis[i * 2], vis[i * 2 + 1] = True, True
        buttons.append(dict(
            label=label, method="update",
            args=[{"visible": vis}, {"scene.zaxis.title": z_title}],
        ))

    fig.update_layout(
        title=dict(
            text=(f'{airfoil_name} 3D Polar  (N-crit: {ncrit})<br>'
                  f'<sub>Thin-Plate Spline 補間 / {valid_count} 収束点</sub>'),
            y=0.97, x=0.02, xanchor='left', yanchor='top',
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
            type="buttons", direction="right", showactive=True,
            x=0.02, y=1.0, xanchor='left', yanchor='bottom',
            buttons=buttons,
        )],
        autosize=True,
        margin=dict(l=0, r=0, b=0, t=60),
    )

    output_html = f'{airfoil_name}_polar_3d.html'
    fig.write_html(output_html, full_html=True, include_plotlyjs='cdn', config={'responsive': True})
    print(f"3D グラフを保存: {output_html}")

    if not no_browser:
        try:
            webbrowser.open('file://' + os.path.abspath(output_html))
        except Exception:
            pass


if __name__ == '__main__':
    mp.freeze_support()
    main()
