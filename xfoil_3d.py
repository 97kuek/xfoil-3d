"""
xfoil_3d.py - XFOIL 3D極曲線 可視化ツール (エントリポイント)
"""
import multiprocessing as mp
from xfoil3d.core import main

if __name__ == '__main__':
    mp.freeze_support()
    main()
