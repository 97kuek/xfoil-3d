import os
import logging
import argparse
import multiprocessing as mp
import tempfile
import shutil
import numpy as np
import pandas as pd
from tqdm import tqdm

from .models import TraceConfig
from .config import load_config, interactive_mode
from .validators import validate_inputs
from .solver import clean_airfoil_dat, calculate_polar
from .physics import interpolate_rbf
from .plotting import create_3d_plot

logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(
        description="XFOIL 3D Polar Visualization Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--config',  type=str, help="前回保存した YAML 設定ファイルのパス")
    parser.add_argument('--verbose', action='store_true', help="詳細ログを表示する")
    cli_args = parser.parse_args()

    # ログ設定
    log_level = logging.DEBUG if cli_args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(levelname)s: %(message)s')

    defaults = None
    if cli_args.config:
        if not os.path.exists(cli_args.config):
            logger.error("設定ファイル '%s' が見つかりません。", cli_args.config)
            return
        defaults = load_config(cli_args.config)

    cfg = interactive_mode(defaults=defaults)

    dat_file                      = cfg.get('dat_file', '')
    re_min, re_max, re_step       = cfg['re_range']
    alpha_min, alpha_max, alpha_step = cfg['alpha_range']
    ncrit                         = cfg.get('ncrit', 9.0)
    xfoil_exe                     = cfg.get('xfoil_exe', 'xfoil.exe')
    show_scatter                  = cfg.get('show_scatter', True)

    errors = validate_inputs(
        dat_file, re_min, re_max, re_step, alpha_min, alpha_max, alpha_step, xfoil_exe
    )
    if errors:
        for err in errors:
            logger.error(err)
        return

    # Re & Alpha 配列生成
    res    = np.arange(re_min,    re_max    + re_step    / 2.0, re_step)
    alphas = np.arange(alpha_min, alpha_max + alpha_step / 2.0, alpha_step)

    airfoil_name  = os.path.splitext(os.path.basename(dat_file))[0]
    dat_file_abs  = os.path.abspath(dat_file)
    xfoil_exe_abs = os.path.abspath(xfoil_exe) if os.path.exists(xfoil_exe) else xfoil_exe

    logger.info("翼型: %s", airfoil_name)
    logger.info("Re 範囲: %.0f ～ %.0f  (ステップ %.0f, 計 %d 点)", re_min, re_max, re_step, len(res))
    logger.info("迎角: %s° ～ %s°  (ステップ %s°)", alpha_min, alpha_max, alpha_step)
    logger.info("N-crit: %s │ プロセス数: %d", ncrit, mp.cpu_count())

    workdir = tempfile.mkdtemp(prefix='_xfoil_tmp_', dir=os.getcwd())
    clean_name = f"clean_{airfoil_name}.dat"
    clean_path = os.path.join(workdir, clean_name)

    try:
        clean_airfoil_dat(dat_file_abs, clean_path)
        tasks = [
            (clean_name, Re, alpha_min, alpha_max, alpha_step, ncrit, xfoil_exe_abs, workdir)
            for Re in res
        ]
        results = []
        with mp.Pool(mp.cpu_count()) as pool:
            for r in tqdm(pool.imap_unordered(calculate_polar, tasks), total=len(tasks), desc="計算中"):
                if r is not None:
                    results.append(r)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if not results:
        logger.error("有効な計算結果がありません。")
        return

    rows = []
    for r in results:
        Re_val = r['Re']
        for j, alpha in enumerate(alphas):
            cl, cd, cm = r['cls'][j], r['cds'][j], r['cms'][j]
            if not np.isnan(cl):
                rows.append({
                    'Airfoil': airfoil_name, 'Re': Re_val, 'Alpha': alpha,
                    'Cl': cl, 'Cd': cd, 'Cm': cm,
                })

    if not rows:
        logger.error("すべての XFOIL 実行が収束しませんでした。")
        return

    df          = pd.DataFrame(rows)
    valid_count = len(df)
    logger.info("\n計算完了: %d / %d 点が収束", valid_count, len(res) * len(alphas))

    # 結果保存用ディレクトリの作成
    output_dir = os.path.join("results", airfoil_name)
    os.makedirs(output_dir, exist_ok=True)

    csv_raw = os.path.join(output_dir, f"{airfoil_name}_polar_raw.csv")
    df.to_csv(csv_raw, index=False)
    logger.info("生データを保存: %s", csv_raw)

    logger.info("RBF（薄板スプライン）補間中...")
    X, Y      = np.meshgrid(alphas, res)
    raw_alpha = df['Alpha'].values
    raw_re    = df['Re'].values

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

    df_interp = pd.DataFrame({
        'Airfoil': airfoil_name, 'Re': Y.ravel(), 'Alpha': X.ravel(),
        'Cl': Z_cl.ravel(), 'Cd': Z_cd.ravel(), 'Cm': Z_cm.ravel(),
    })
    csv_interp = os.path.join(output_dir, f"{airfoil_name}_polar_interp.csv")
    df_interp.to_csv(csv_interp, index=False)
    logger.info("補間グリッドを保存: %s", csv_interp)

    trace_configs = [
        TraceConfig(Z_cl, df['Cl'].values, 'Viridis', 'Cl (Lift)',          'Lift Coefficient (Cl)'),
        TraceConfig(Z_cd, df['Cd'].values, 'Cividis', 'Cd (Drag)',          'Drag Coefficient (Cd)'),
        TraceConfig(Z_cm, df['Cm'].values, 'Plasma',  'Cm (Moment)',        'Moment Coefficient (Cm)'),
        TraceConfig(Z_ld, raw_ld_vals,     'Inferno', 'Cl/Cd (Efficiency)', 'Lift-to-Drag Ratio (Cl/Cd)'),
    ]

    create_3d_plot(
        airfoil_name, ncrit, X, Y, trace_configs, raw_alpha, raw_re,
        show_scatter, valid_count, output_dir=output_dir
    )
    logger.info("完了 (保存先: %s)", output_dir)

if __name__ == '__main__':
    main()
