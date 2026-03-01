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

## 補間アルゴリズム

### なぜ補間が必要か

XFOIL は全ての迎角で収束するわけではなく、特に高迎角・低 Re では失敗することがあります。  
3D サーフェスを滑らかに描画するには、失敗点を物理的に妥当な値で補う必要があります。

### 薄板スプライン（Thin-Plate Spline）

本ツールは **Thin-Plate Spline（TPS）** を基底関数とする RBF（Radial Basis Function）補間を採用しています。

#### 最小化する汎関数

TPS は2次元の「曲げエネルギー」を最小化する関数 $f(x, y)$ を求めます：

$$E[f] = \iint \left[ \left(\frac{\partial^2 f}{\partial x^2}\right)^2 + 2\left(\frac{\partial^2 f}{\partial x \partial y}\right)^2 + \left(\frac{\partial^2 f}{\partial y^2}\right)^2 \right] dx\, dy$$

曲げエネルギー最小化により、データ点間を**最も滑らかに**補間します（折れ曲がりが最小）。

#### 基底関数

$$\phi(r) = r^2 \log r, \quad r = \|P_i - P_j\|$$

$r$ はデータ点間のユークリッド距離です。RBF 補間の解は次の形で表されます：

$$f(x, y) = \sum_{i=1}^{N} w_i \, \phi\!\left(\|P - P_i\|\right) + p(x, y)$$

$w_i$ は重み係数、$p(x, y)$ は線形多項式項（アフィン変換の自由度）。

#### 性質

| 性質 | 内容 |
|------|------|
| **補間通過** | `smooth=0.0` により全収束点を厳密に通過 |
| **物理的滑らかさ** | 曲げエネルギー最小 → 空力係数の急激な変化を回避 |
| **散乱データ対応** | 格子点以外の不規則配置データにも適用可能 |
| **外挿の注意** | 収束点の範囲外では振動が生じる場合あり |

### スケール正規化

Re は $O(10^5)$、$\alpha$ は $O(10)$ と桁が大きく異なるため、  
ユークリッド距離が Re 方向に支配される問題が起きます。  
両軸を $[0, 1]$ に正規化することでこれを解消します：

$$\hat{\alpha} = \frac{\alpha - \alpha_{\min}}{\alpha_{\max} - \alpha_{\min}}, \quad
\widehat{Re} = \frac{Re - Re_{\min}}{Re_{\max} - Re_{\min}}$$

## 出力ファイル

| ファイル | 内容 |
|----------|------|
| `<airfoil>_polar_3d.html` | 対話的 3D グラフ（フルスクリーン） |
| `<airfoil>_polar_raw.csv` | XFOIL 収束点の生データ |
| `<airfoil>_polar_interp.csv` | TPS 補間後のグリッドデータ |

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
- 計算によっては収束しないケースがあります。収束失敗点は TPS 補間で補われます。
- レイノルズ数・迎角の範囲を広げると計算時間が増加します。
- TPS 補間は収束点の**範囲内**では優れた精度を発揮しますが、外挿には向きません。

## ライセンス

MIT License
