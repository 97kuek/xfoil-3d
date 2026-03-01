# xfoil-3d

XFOIL を用いて翼型の3次元極曲線（Cl / Cd / Cm / Cl/Cd）を計算・可視化するCLIツールです。  
複数のレイノルズ数に対して並列計算を行い、Thin-Plate Spline (RBF) 補間によって滑らかな3Dサーフェスを生成します。

## 機能

- 複数レイノルズ数を **マルチプロセス** で並列シミュレーション
- 収束点を **RBF（Thin-Plate Spline）補間** でグリッドに補間
- **Plotly** による対話的なフルスクリーン 3D グラフ（HTML出力）
- Cl・Cd・Cm・Cl/Cd の切り替えボタン付き
- **インタラクティブモード**：引数なしで起動すると矢印キーで選択できる対話型プロンプト
- **YAML 設定ファイル**：パラメータを保存・再利用可能

## 必要環境

| ツール | バージョン |
|--------|-----------|
| Python | 3.9 以上 |
| XFOIL  | 6.99（`xfoil.exe` をプロジェクト直下に配置） |

### Python パッケージ

```powershell
pip install numpy pandas plotly scipy tqdm questionary PyYAML
```

## 使い方

### ① インタラクティブモード（引数なしで起動）

```powershell
python xfoil_3d.py
```

矢印キーで翼型ファイルを選択し、各パラメータを順番に入力できます。  
終了時に設定を `config.yaml` へ保存するか確認されます。

### ② 設定ファイルを使う（推奨）

```powershell
# 前回保存した設定で実行
python xfoil_3d.py --config config.yaml

# 設定ファイルの一部だけ上書きして実行
python xfoil_3d.py --config config.yaml --ncrit 7
```

`config.yaml` の例:

```yaml
dat_file: Airfoils/NACA0009.dat
re_range: [100000, 500000, 5]
alpha_range: [-10, 15, 1]
ncrit: 9.0
xfoil_exe: xfoil.exe
no_browser: false
```

### ③ 従来どおりの CLI（後方互換）

```powershell
python xfoil_3d.py --dat_file Airfoils/NACA0009.dat --re_range 100000 500000 5 --alpha_range -10 15 1 --ncrit 9
```

### 引数一覧

| 引数 | 説明 |
|------|------|
| `--config FILE` | YAML 設定ファイルのパス |
| `--dat_file` | 翼型 `.dat` ファイルのパス |
| `--re_range MIN MAX COUNT` | レイノルズ数の範囲と分割数 |
| `--alpha_range MIN MAX STEP` | 迎角の範囲とステップ（°） |
| `--ncrit` | N-crit 値（デフォルト: 9.0） |
| `--xfoil_exe` | XFOIL 実行ファイルのパス |
| `--no_browser` | 計算後にブラウザを自動で開かない |
| `--save_config FILE` | 現在のCLI引数を YAML に保存して終了 |

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
├── config.yaml        # 設定ファイル（インタラクティブモードで自動生成）
├── README.md
└── .gitignore
```

## 注意事項

- `xfoil.exe` は Windows 版 XFOIL を別途入手してプロジェクト直下に配置してください。
- 計算によっては収束しないケースがあります。収束失敗点は補間で補われます。
- レイノルズ数・迎角の範囲を広げると計算時間が増加します。

## ライセンス

MIT License
