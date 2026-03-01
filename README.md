# xfoil-3d

XFOILを用いて翼型の3次元極曲線を計算・可視化するCLIツール。  
複数のレイノルズ数に対して並列計算を行い、Thin-Plate Spline (RBF) 補間によって滑らかな3Dサーフェスを生成する。

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

### 起動方法

```powershell
# 引数なしで起動 → インタラクティブモード
python xfoil_3d.py

# 前回保存した設定をデフォルト値として読み込んで起動
python xfoil_3d.py --config config.yaml
```

起動すると矢印キーで翼型ファイルを選択し、各パラメータを順番に入力できます。  
終了時に設定を `config.yaml` へ保存するか確認されます。  
次回 `--config config.yaml` を指定すれば、前回値がデフォルトとして表示されます。

### インタラクティブモードの入力項目

| 項目 | 説明 | 例 |
|------|------|----|
| 翼型ファイル | Airfoils/ から選択または手動入力 | `Airfoils/NACA0009.dat` |
| Re 最小値 | レイノルズ数の最小値 | `100000` |
| Re 最大値 | レイノルズ数の最大値 | `500000` |
| Re ステップ幅 | Re のステップ幅（等間隔で自動生成） | `50000` |
| 迎角 最小 (deg) | 解析する最小迎角 | `-10` |
| 迎角 最大 (deg) | 解析する最大迎角 | `15` |
| 迎角 ステップ (deg) | 迎角のステップ幅 | `0.5` |
| N-crit 値 | 乱流遷移感度（低いほど早期遷移） | `9.0` |
| XFOIL 実行ファイル | xfoil.exe のパス | `xfoil.exe` |

### `config.yaml` の例

```yaml
dat_file: Airfoils/DAE31.dat
re_range: [100000, 500000, 50000]   # [min, max, step_width]
alpha_range: [-3, 15, 0.5]
ncrit: 9.0
xfoil_exe: xfoil.exe
no_browser: false
```

> [!NOTE]
> `re_range` の第3要素は **ステップ幅**（例: 50000）です。`[100000, 500000, 50000]` と指定すると Re = 100000, 150000, …, 500000 の9点で計算します。

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
