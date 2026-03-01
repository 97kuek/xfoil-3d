"""
xfoil_3d.py - XFOIL 3D極曲線 可視化ツール

XFOILを使って翼型のCl・Cd・Cm・Cl/Cdを複数レイノルズ数で並列計算し、
Thin-Plate Spline (RBF) 補間で3D極曲線サーフェスをHTML形式で出力する。
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import os
import subprocess
import tempfile
import uuid
import webbrowser
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yaml
from scipy.interpolate import RBFInterpolator
from tqdm import tqdm

try:
    import questionary
    QUESTIONARY_AVAILABLE = True
except ImportError:
    QUESTIONARY_AVAILABLE = False

# ─────────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────────

XFOIL_TIMEOUT    = 180    # XFOIL 1プロセスあたりのタイムアウト（秒）
RAW_MARKER_SIZE  = 2      # 生データ散布点のサイズ
RAW_MARKER_ALPHA = 0.25   # 生データ散布点の不透明度

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# データ構造
# ─────────────────────────────────────────────────────────────

class TraceConfig(NamedTuple):
    """3D グラフの1指標分の設定。"""
    surf_z:     np.ndarray
    raw_z:      np.ndarray
    colorscale: str
    label:      str
    z_title:    str


# ─────────────────────────────────────────────────────────────
# XFOIL 実行・解析
# ─────────────────────────────────────────────────────────────

def calculate_polar(args: tuple) -> dict | None:
    """
    マルチプロセス用ワーカー関数。
    指定されたレイノルズ数に対して XFOIL を実行し、
    Cl・Cd・Cm を alpha ごとに返す。

    XFOIL（Fortran製）はファイルパスを固定長バッファ（約80文字）で読み込む。
    そのため LOAD・PACC コマンドに渡すパスは短く保つ必要がある。
    - dat_file  : xfoil_exe と同じディレクトリへの相対パス（または短い絶対パス）
    - polar_file: カレントディレクトリへの相対パス（ファイル名のみ）
    - dump_file : 同上
    subprocess.run に cwd を渡してワーカー側のカレントディレクトリを固定する。
    """
    dat_file, Re, alpha_min, alpha_max, alpha_step, ncrit, xfoil_exe, run_dir = args

    re_int = int(Re)   # np.float64 → int でファイル名を短くする
    uid    = uuid.uuid4().hex[:8]
    # ファイル名は短い相対パス（run_dir 内）で渡す
    polar_name = f"p{re_int}_{uid}.txt"
    dump_name  = f"d{re_int}_{uid}.txt"
    polar_file = os.path.join(run_dir, polar_name)
    dump_file  = os.path.join(run_dir, dump_name)

    commands = (
        f"PLOP\nG F\n\n"
        f"LOAD {dat_file}\nPANE\nOPER\nITER 200\n"
        f"Visc {re_int}\nVPAR\nN {ncrit}\n\n"
        f"PACC\n{polar_name}\n{dump_name}\n"
        f"ASEQ {alpha_min} {alpha_max} {alpha_step}\n"
        f"PACC\n\nQUIT\n"
    )

    try:
        subprocess.run(
            [xfoil_exe],
            input=commands,
            text=True,
            capture_output=True,
            timeout=XFOIL_TIMEOUT,
            cwd=run_dir,   # ワーカーのカレントを run_dir に固定
        )
    except subprocess.TimeoutExpired:
        logger.warning("Re=%d: XFOIL がタイムアウトしました（%d 秒）", re_int, XFOIL_TIMEOUT)
        return None
    except Exception as e:
        logger.warning("Re=%d: XFOIL 実行に失敗しました: %s", re_int, e)
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
        except Exception as e:
            logger.warning("Re=%d: 極ファイルの読み込みに失敗しました: %s", re_int, e)
        finally:
            for path in (polar_file, dump_file):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

    return {
        'Re':     Re,
        'alphas': alphas,
        'cls':    cl_results,
        'cds':    cd_results,
        'cms':    cm_results,
    }



def clean_airfoil_dat(in_path: str, out_path: str) -> None:
    """
    XFOIL 用に .dat ファイルを正規化する。
    タブを空白に置換し、座標行を「 x  y」形式に統一する。

    先頭行がヘッダ文字列（非数値）の場合はそのまま出力し、
    数値2列で始まる場合（ヘッダなし形式）は翼型名として空の 1 行を挿入する。
    """
    def _is_coord_line(line: str) -> bool:
        """行が数値2列の座標行かどうかを判定する。"""
        parts = line.split()
        if len(parts) < 2:
            return False
        try:
            float(parts[0])
            float(parts[1])
            return True
        except ValueError:
            return False

    try:
        with open(in_path, encoding='utf-8', errors='ignore') as f:
            lines = [l.replace('\t', ' ').strip() for l in f.readlines()]

        # 空行を除去し、先頭の実質的な行を取得
        non_empty = [l for l in lines if l]
        if not non_empty:
            return

        with open(out_path, 'w', encoding='utf-8') as f:
            if _is_coord_line(non_empty[0]):
                # ヘッダなし: 翼型名として空文字を1行挿入
                f.write('\n')
                for line in non_empty:
                    parts = line.split()
                    if len(parts) >= 2:
                        f.write(f" {parts[0]}  {parts[1]}\n")
            else:
                # 先頭行をヘッダとして出力
                f.write(non_empty[0] + '\n')
                for line in non_empty[1:]:
                    parts = line.split()
                    if len(parts) >= 2:
                        f.write(f" {parts[0]}  {parts[1]}\n")
    except Exception as e:
        logger.warning(".dat ファイルの正規化に失敗しました: %s", e)


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
        smoothing=0.0 により、全データ点を厳密に通過する補間（スムージングなし）。

    スケール正規化について:
        Re は O(10⁵)、alpha は O(10) と桁が大きく異なる。
        ユークリッド距離の計算が Re 方向で支配的になるのを防ぐため、
        両軸を [0, 1] に正規化してから補間する。

    Note:
        scipy.interpolate.Rbf (旧 API) から RBFInterpolator (SciPy 1.7+) へ移行済み。
    """
    points = np.column_stack([x_norm, y_norm])
    rbf    = RBFInterpolator(points, z_values, kernel='thin_plate_spline', smoothing=0.0)
    query  = np.column_stack([grid_x_norm.ravel(), grid_y_norm.ravel()])
    return rbf(query).reshape(grid_x_norm.shape)


# ─────────────────────────────────────────────────────────────
# バリデーション
# ─────────────────────────────────────────────────────────────

def validate_inputs(
    dat_file: str,
    re_min: float, re_max: float, re_step: float,
    alpha_min: float, alpha_max: float, alpha_step: float,
    xfoil_exe: str,
) -> list[str]:
    """
    入力パラメータを検証し、エラーメッセージのリストを返す。
    リストが空なら全項目が有効。
    """
    errors: list[str] = []

    if not os.path.exists(dat_file):
        errors.append(f"ファイル '{dat_file}' が見つかりません。")

    if re_min <= 0 or re_max <= 0:
        errors.append("レイノルズ数は正の値を指定してください。")
    elif re_min >= re_max:
        errors.append("Re 最小値 < Re 最大値 になるよう指定してください。")

    if re_step <= 0:
        errors.append("Re ステップ幅は正の値を指定してください。")

    if alpha_min >= alpha_max:
        errors.append("迎角 最小値 < 最大値 になるよう指定してください。")

    if alpha_step <= 0:
        errors.append("迎角ステップは正の値を指定してください。")

    if not _xfoil_exists(xfoil_exe):
        errors.append(f"XFOIL 実行ファイル '{xfoil_exe}' が見つかりません。")

    return errors


def _xfoil_exists(xfoil_exe: str) -> bool:
    """XFOIL 実行ファイルが利用可能かどうかを確認する。"""
    if os.path.exists(xfoil_exe):
        return True
    # PATH に通っている場合を考慮
    try:
        subprocess.run(
            [xfoil_exe],
            input="QUIT\n",
            text=True,
            capture_output=True,
            timeout=2,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# 設定ファイル (YAML)
# ─────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    """YAML ファイルから設定を読み込む。"""
    with open(config_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    logger.info("設定ファイルを読み込みました: %s", config_path)
    return cfg


def save_config(config_path: str, cfg: dict) -> None:
    """設定を YAML ファイルに保存する。"""
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    logger.info("設定を保存しました: %s", config_path)


# ─────────────────────────────────────────────────────────────
# インタラクティブモード
# ─────────────────────────────────────────────────────────────

def interactive_mode(defaults: dict | None = None) -> dict:
    """
    対話式でパラメータを入力するモード。
    defaults に config から読み込んだ値を渡すと、デフォルト値として事前入力される。
    questionary がインストールされていない場合は標準 input() にフォールバックする。
    バリデーションエラーがある場合はエラーを表示して再入力を促す。
    """
    print("\n=== XFOIL 3D Polar - インタラクティブモード ===")

    # defaults からデフォルト値を取り出す
    d = defaults or {}
    d_re   = d.get('re_range',    [100000, 500000, 50000])
    d_alp  = d.get('alpha_range', [-10, 15, 1])

    airfoil_dir = Path('Airfoils')
    dat_files   = sorted(str(p) for p in airfoil_dir.glob('*.dat')) if airfoil_dir.exists() else []

    if QUESTIONARY_AVAILABLE:
        cfg = _interactive_questionary(d, d_re, d_alp, dat_files)
    else:
        cfg = _interactive_input(d, d_re, d_alp, dat_files)

    # バリデーション
    re_min, re_max, re_step = cfg['re_range']
    a_min, a_max, a_step    = cfg['alpha_range']
    errors = validate_inputs(
        cfg['dat_file'], re_min, re_max, re_step, a_min, a_max, a_step, cfg['xfoil_exe']
    )
    if errors:
        print("\n[エラー] 以下の問題が検出されました:")
        for err in errors:
            print(f"  ✗ {err}")
        print()

    return cfg


def _interactive_questionary(d: dict, d_re: list, d_alp: list, dat_files: list) -> dict:
    """questionary を使ったインタラクティブ入力。"""
    # 翼型ファイル選択
    if dat_files:
        choices       = dat_files + ['[手動入力]']
        default_dat   = d.get('dat_file')
        default_choice = default_dat if (default_dat and default_dat in dat_files) else choices[0]
        dat_choice    = questionary.select(
            "翼型ファイルを選択してください:",
            choices=choices,
            default=default_choice,
        ).ask()
        dat_file = questionary.text("翼型ファイルのパスを入力:").ask() if dat_choice == '[手動入力]' else dat_choice
    else:
        dat_file = questionary.text(
            "翼型ファイルのパスを入力:",
            default=d.get('dat_file', ''),
        ).ask()

    re_min    = float(questionary.text("レイノルズ数 最小値:",    default=str(int(d_re[0]))).ask())
    re_max    = float(questionary.text("レイノルズ数 最大値:",    default=str(int(d_re[1]))).ask())
    re_step   = float(questionary.text("レイノルズ数 ステップ幅:", default=str(int(d_re[2]))).ask())
    a_min     = float(questionary.text("迎角 最小 (deg):",        default=str(d_alp[0])).ask())
    a_max     = float(questionary.text("迎角 最大 (deg):",        default=str(d_alp[1])).ask())
    a_step    = float(questionary.text("迎角 ステップ (deg):",    default=str(d_alp[2])).ask())
    ncrit     = float(questionary.text("N-crit 値:",              default=str(d.get('ncrit', 9.0))).ask())
    xfoil_exe = questionary.text(
        "XFOIL 実行ファイルパス:",
        default=d.get('xfoil_exe', 'xfoil.exe'),
    ).ask()
    show_scatter = questionary.confirm(
        "3Dグラフに生データ点（散布図）を表示しますか?",
        default=d.get('show_scatter', True),
    ).ask()

    cfg = {
        'dat_file':     dat_file,
        're_range':     [re_min, re_max, re_step],
        'alpha_range':  [a_min, a_max, a_step],
        'ncrit':        ncrit,
        'xfoil_exe':    xfoil_exe,
        'show_scatter': show_scatter,
    }

    # 設定の保存確認
    if questionary.confirm("この設定を YAML ファイルに保存しますか?", default=True).ask():
        fname = questionary.text("保存先ファイル名:", default="config.yaml").ask()
        save_config(fname, cfg)

    print()
    return cfg


def _interactive_input(d: dict, d_re: list, d_alp: list, dat_files: list) -> dict:
    """questionary 非インストール時のフォールバック（標準 input）。"""
    # 翼型ファイル選択
    if dat_files:
        print("利用可能な翼型ファイル:")
        for i, f in enumerate(dat_files):
            print(f"  [{i}] {f}")
        idx      = input("番号を選択 (手動入力は Enter): ").strip()
        dat_file = dat_files[int(idx)] if idx.isdigit() and int(idx) < len(dat_files) else input("ファイルパス: ").strip()
    else:
        dat_file = input(f"翼型ファイルのパスを入力 [{d.get('dat_file', '')}]: ").strip() or d.get('dat_file', '')

    re_min    = float(input(f"レイノルズ数 最小値 [{int(d_re[0])}]: ").strip() or d_re[0])
    re_max    = float(input(f"レイノルズ数 最大値 [{int(d_re[1])}]: ").strip() or d_re[1])
    re_step   = float(input(f"レイノルズ数 ステップ幅 [{int(d_re[2])}]: ").strip() or d_re[2])
    a_min     = float(input(f"迎角 最小 (deg) [{d_alp[0]}]: ").strip() or d_alp[0])
    a_max     = float(input(f"迎角 最大 (deg) [{d_alp[1]}]: ").strip() or d_alp[1])
    a_step    = float(input(f"迎角 ステップ (deg) [{d_alp[2]}]: ").strip() or d_alp[2])
    ncrit     = float(input(f"N-crit 値 [{d.get('ncrit', 9.0)}]: ").strip() or d.get('ncrit', 9.0))
    xfoil_exe = input(f"XFOIL 実行ファイルパス [{d.get('xfoil_exe', 'xfoil.exe')}]: ").strip() or d.get('xfoil_exe', 'xfoil.exe')
    show_scatter_default = 'Y' if d.get('show_scatter', True) else 'N'
    show_scatter = (input(f"3Dグラフに生データ点を表示しますか？ [Y/n] [{show_scatter_default}]: ").strip().lower() != 'n')

    cfg = {
        'dat_file':     dat_file,
        're_range':     [re_min, re_max, re_step],
        'alpha_range':  [a_min, a_max, a_step],
        'ncrit':        ncrit,
        'xfoil_exe':    xfoil_exe,
        'show_scatter': show_scatter,
    }

    # 設定の保存確認
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
        description="XFOIL 3D Polar Visualization Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="設定ファイルを指定するとその値がデフォルトとして事前入力されます。\n例: python xfoil_3d.py --config config.yaml",
    )
    parser.add_argument('--config',  type=str, help="前回保存した YAML 設定ファイルのパス")
    parser.add_argument('--verbose', action='store_true', help="詳細ログを表示する")
    cli_args = parser.parse_args()

    # ログ設定
    log_level = logging.DEBUG if cli_args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(levelname)s: %(message)s')

    # config が指定されていれば読み込んでデフォルト値として渡す
    defaults = None
    if cli_args.config:
        if not os.path.exists(cli_args.config):
            logger.error("設定ファイル '%s' が見つかりません。", cli_args.config)
            return
        defaults = load_config(cli_args.config)

    cfg = interactive_mode(defaults=defaults)

    # ── cfg から変数を取り出す ──
    dat_file                      = cfg.get('dat_file', '')
    re_min, re_max, re_step       = cfg['re_range']
    alpha_min, alpha_max, alpha_step = cfg['alpha_range']
    ncrit                         = cfg.get('ncrit', 9.0)
    xfoil_exe                     = cfg.get('xfoil_exe', 'xfoil.exe')
    show_scatter                  = cfg.get('show_scatter', True)

    # ── バリデーション（再チェック、エラーがあれば終了）──
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
    print()

    # ── .dat ファイルの正規化 & 計算実行 ──
    # XFOILのLOAD/PACCコマンドはFortranの固定長バッファ（約80文字）で
    # パスを読み込むため、長いパスだと途中で切れて失敗する。
    # → subprocess.run の cwd=workdir でXFOILのカレントをworkdirに固定し、
    #   LOADにはclean.datの「ファイル名のみ」を渡すことで問題を回避する。
    import shutil
    workdir         = tempfile.mkdtemp(prefix='_xfoil_tmp_', dir=os.getcwd())
    clean_name      = f"clean_{airfoil_name}.dat"           # ファイル名のみ（短い）
    clean_path      = os.path.join(workdir, clean_name)     # 実際の書き込み先

    try:
        clean_airfoil_dat(dat_file_abs, clean_path)

        tasks = [
            # dat_file は workdir からの相対名（XFOILのcwdがworkdirなので直接参照できる）
            (clean_name, Re, alpha_min, alpha_max, alpha_step, ncrit, xfoil_exe_abs, workdir)
            for Re in res
        ]
        results = []
        with mp.Pool(mp.cpu_count()) as pool:
            for r in tqdm(pool.imap_unordered(calculate_polar, tasks), total=len(tasks), desc="計算中"):
                if r is not None:
                    results.append(r)
    finally:
        # workdir ごと削除して一時ファイルを確実にクリーンアップ
        shutil.rmtree(workdir, ignore_errors=True)

    if not results:
        logger.error("有効な計算結果がありません。")
        return

    # ── 結果を DataFrame に集約 ──
    rows = []
    for r in results:
        Re_val = r['Re']
        for j, alpha in enumerate(alphas):
            cl, cd, cm = r['cls'][j], r['cds'][j], r['cms'][j]
            if not np.isnan(cl):
                rows.append({
                    'Airfoil': airfoil_name,
                    'Re':      Re_val,
                    'Alpha':   alpha,
                    'Cl':      cl,
                    'Cd':      cd,
                    'Cm':      cm,
                })

    if not rows:
        logger.error("すべての XFOIL 実行が収束しませんでした。")
        return

    df          = pd.DataFrame(rows)
    valid_count = len(df)
    total_count = len(res) * len(alphas)
    logger.info("\n計算完了: %d / %d 点が収束", valid_count, total_count)

    csv_raw = f"{airfoil_name}_polar_raw.csv"
    df.to_csv(csv_raw, index=False)
    logger.info("生データを保存: %s", csv_raw)

    # ── RBF 補間（Thin-Plate Spline） ──
    logger.info("RBF（薄板スプライン）補間中...")

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

    # 補間グリッドを CSV に保存
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
    logger.info("補間グリッドを保存: %s", csv_interp)

    # ── 3D プロット作成 ──
    trace_configs = [
        TraceConfig(Z_cl, df['Cl'].values, 'Viridis', 'Cl (Lift)',          'Lift Coefficient (Cl)'),
        TraceConfig(Z_cd, df['Cd'].values, 'Cividis', 'Cd (Drag)',          'Drag Coefficient (Cd)'),
        TraceConfig(Z_cm, df['Cm'].values, 'Plasma',  'Cm (Moment)',        'Moment Coefficient (Cm)'),
        TraceConfig(Z_ld, raw_ld_vals,     'Inferno', 'Cl/Cd (Efficiency)', 'Lift-to-Drag Ratio (Cl/Cd)'),
    ]

    # 生データ点のスタイル: 小さく・半透明で補間面を隠さない
    raw_marker = dict(size=RAW_MARKER_SIZE, color=f'rgba(0, 0, 0, {RAW_MARKER_ALPHA})')

    fig = go.Figure()

    # --- トレース追加 ---
    # show_scatter=True  → 補間面 + 生データ点（Surface + Scatter3d）で 2本/指標
    # show_scatter=False → 補間面のみ（Surface のみ）で 1本/指標
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

    # 表示切り替えボタン
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
            pad=dict(t=8),  # 上端から 8px の余白でクリッピングを防ぐ
        ),
        scene=dict(
            xaxis_title='Alpha (deg)',
            yaxis_title='Reynolds Number',
            zaxis_title='Lift Coefficient (Cl)',
            xaxis=dict(nticks=10),
            yaxis=dict(nticks=10),
            zaxis=dict(nticks=10),
        ),
        # ボタンを右上に配置して、左上のタイトルと重ならないようにする
        updatemenus=[dict(
            type="buttons", direction="left", showactive=True,
            x=0.99, xanchor='right',
            y=0.97, yanchor='top',
            pad=dict(t=8, b=0),
            buttons=buttons,
        )],
        autosize=True,
        margin=dict(l=0, r=0, b=0, t=100),  # タイトル2行分 + ボタン分を確保
    )

    output_html = f'{airfoil_name}_polar_3d.html'
    fig.write_html(output_html, full_html=True, include_plotlyjs='cdn', config={'responsive': True})
    logger.info("3D グラフを保存: %s", output_html)

    # ブラウザで自動表示
    try:
        webbrowser.open('file://' + os.path.abspath(output_html))
    except Exception:
        pass


if __name__ == '__main__':
    mp.freeze_support()
    main()
