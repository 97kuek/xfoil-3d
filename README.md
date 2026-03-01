# xfoil-3d

XFOIL を用いて翼型の3次元極曲線（Cl / Cd / Cm / Cl/Cd）を計算・可視化するCLIツールです。  
複数のレイノルズ数に対して並列計算を行い、Thin-Plate Spline (RBF) 補間によって滑らかな3Dサーフェスを生成します。

## 機能

- 複数レイノルズ数を **マルチプロセス** で並列シミュレーション
- 収束点を **RBF（Thin-Plate Spline）補間** でグリッドに補間
- **Plotly** による対話的なフルスクリーン 3D グラフ（HTML出力）
- Cl・Cd・Cm・Cl/Cd の切り替えボタン付き
- 生データを CSV に出力（`*_polar_raw.csv` / `*_polar_interp.csv`）

## 必要環境

| ツール | バージョン |
|--------|-----------|
| Python | 3.9 以上 |
| XFOIL  | 6.99（`xfoil.exe` をプロジェクト直下に配置） |

### Python パッケージ

```bash
pip install numpy pandas plotly scipy tqdm
```

## 使い方

```powershell
# PowerShell（Windows）
python xfoil_3d.py --dat_file Airfoils/NACA0009.dat --re_range 100000 500000 5 --alpha_range -10 15 1 --ncrit 9

# PowerShell（複数行に分けたい場合はバッククォートで継続）
python xfoil_3d.py `
  --dat_file Airfoils/NACA0009.dat `
  --re_range 100000 500000 5 `
  --alpha_range -10 15 1 `
  --ncrit 9
```

```bash
# bash / Linux / macOS
python xfoil_3d.py \
  --dat_file Airfoils/NACA0009.dat \
  --re_range 100000 500000 5 \
  --alpha_range -10 15 1 \
  --ncrit 9
```

### 引数一覧

| 引数 | 説明 | 例 |
|------|------|----|
| `--dat_file` | 翼型 `.dat` ファイルのパス（必須） | `Airfoils/NACA0009.dat` |
| `--re_range MIN MAX COUNT` | レイノルズ数の範囲と分割数（必須） | `100000 500000 5` |
| `--alpha_range MIN MAX STEP` | 迎角の範囲とステップ（°）（必須） | `-10 15 1` |
| `--ncrit` | XFOIL の N-crit 値（デフォルト: 9.0） | `9` |
| `--xfoil_exe` | XFOIL 実行ファイルのパス（デフォルト: `xfoil.exe`） | `./xfoil.exe` |
| `--no_browser` | 計算後にブラウザを自動で開かない | — |

## 出力ファイル

| ファイル | 内容 |
|----------|------|
| `<airfoil>_polar_3d.html` | 対話的 3D グラフ（フルスクリーン） |
| `<airfoil>_polar_raw.csv` | XFOIL 収束点の生データ |
| `<airfoil>_polar_interp.csv` | RBF 補間後のグリッドデータ |

## ディレクトリ構成

```
xfoil-3d/
├── Airfoils/          # 翼型 .dat ファイル置き場
├── xfoil_3d.py        # メインスクリプト
├── xfoil.exe          # XFOIL 実行ファイル（自分で用意）
├── README.md
└── .gitignore
```

## 注意事項

- `xfoil.exe` は Windows 版 XFOIL を別途入手してプロジェクト直下に配置してください。
- 計算によっては収束しないケースがあります。収束失敗点は補間で補われます。
- レイノルズ数・迎角の範囲を広げると計算時間が増加します。

## ライセンス

MIT License
