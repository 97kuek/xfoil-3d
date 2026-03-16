import os
import subprocess

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
        errors.append("Re数は正の値を指定してください。")
    elif re_min >= re_max:
        errors.append("Re 最小値 < Re 最大値 になるよう指定してください。")

    if re_step <= 0:
        errors.append("Re ステップ幅は正の値を指定してください。")

    if alpha_min >= alpha_max:
        errors.append("迎角 最小値 < 最大値 になるよう指定してください。")

    if alpha_step <= 0:
        errors.append("迎角ステップは正の値を指定してください。")

    if not xfoil_exists(xfoil_exe):
        errors.append(f"XFOIL 実行ファイル '{xfoil_exe}' が見つかりません。")

    return errors


def xfoil_exists(xfoil_exe: str) -> bool:
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
