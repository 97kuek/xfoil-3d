import os
import logging
import yaml
from pathlib import Path

try:
    import questionary
    QUESTIONARY_AVAILABLE = True
except ImportError:
    QUESTIONARY_AVAILABLE = False

from .validators import validate_inputs

logger = logging.getLogger(__name__)

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


def interactive_mode(defaults: dict | None = None) -> dict:
    """
    対話式でパラメータを入力するモード。
    defaults に config から読み込んだ値を渡すと、デフォルト値として事前入力される。
    questionary がインストールされていない場合は標準 input() にフォールバックする。
    バリデーションエラーがある場合はエラーを表示して再入力を促す。
    """
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
            "翼型ファイルを選択:",
            choices=choices,
            default=default_choice,
        ).ask()
        dat_file = questionary.text("翼型ファイルのパスを入力:").ask() if dat_choice == '[手動入力]' else dat_choice
    else:
        dat_file = questionary.text(
            "翼型ファイルのパスを入力:",
            default=d.get('dat_file', ''),
        ).ask()

    re_min    = float(questionary.text("Re数 最小値:",    default=str(int(d_re[0]))).ask())
    re_max    = float(questionary.text("Re数 最大値:",    default=str(int(d_re[1]))).ask())
    re_step   = float(questionary.text("Re数 ステップ幅:", default=str(int(d_re[2]))).ask())
    a_min     = float(questionary.text("迎角 最小 (deg):",        default=str(d_alp[0])).ask())
    a_max     = float(questionary.text("迎角 最大 (deg):",        default=str(d_alp[1])).ask())
    a_step    = float(questionary.text("迎角 ステップ (deg):",    default=str(d_alp[2])).ask())
    ncrit     = float(questionary.text("N-crit 値:",              default=str(d.get('ncrit', 9.0))).ask())
    xfoil_exe = questionary.text(
        "XFOIL 実行ファイルパス:",
        default=d.get('xfoil_exe', 'xfoil.exe'),
    ).ask()
    show_scatter = questionary.confirm(
        "散布図の表示",
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
    if questionary.confirm("設定をYAMLファイルに保存", default=True).ask():
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

    re_min    = float(input(f"Re数 最小値 [{int(d_re[0])}]: ").strip() or d_re[0])
    re_max    = float(input(f"Re数 最大値 [{int(d_re[1])}]: ").strip() or d_re[1])
    re_step   = float(input(f"Re数 ステップ幅 [{int(d_re[2])}]: ").strip() or d_re[2])
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
