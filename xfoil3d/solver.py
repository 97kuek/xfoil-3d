import os
import subprocess
import uuid
import logging
import numpy as np

logger = logging.getLogger(__name__)

XFOIL_TIMEOUT = 180

def calculate_polar(args: tuple) -> dict | None:
    """指定されたレイノルズ数に対して XFOIL を実行し、Cl・Cd・Cm を返す。"""
    dat_file, Re, alpha_min, alpha_max, alpha_step, ncrit, xfoil_exe, run_dir = args

    re_int = int(Re)
    uid    = uuid.uuid4().hex[:8]
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
            cwd=run_dir,
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
                            cm = float(parts[4])
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
    """XFOIL 用に .dat ファイルを正規化する。"""
    def _is_coord_line(line: str) -> bool:
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

        non_empty = [l for l in lines if l]
        if not non_empty:
            return

        with open(out_path, 'w', encoding='utf-8') as f:
            if _is_coord_line(non_empty[0]):
                f.write('\n')
                for line in non_empty:
                    parts = line.split()
                    if len(parts) >= 2:
                        f.write(f" {parts[0]}  {parts[1]}\n")
            else:
                f.write(non_empty[0] + '\n')
                for line in non_empty[1:]:
                    parts = line.split()
                    if len(parts) >= 2:
                        f.write(f" {parts[0]}  {parts[1]}\n")
    except Exception as e:
        logger.warning(".dat ファイルの正規化に失敗しました: %s", e)
