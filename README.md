# xfoil-3d

XFOILを用いて翼型の3次元極曲線（Cl, Cd, Cm, Cl/Cd）を計算・可視化するCLIツール。  
複数のRe数に対して並列計算を行い、Thin-Plate Spline (RBF) 補間によって3Dサーフェスを生成する。

![3D極曲線](./images/3D極曲線.png)

## プログラム構成

```text
xfoil-3d/
├── xfoil_3d.py          # エントリポイント（実行用ラッパー）
└── xfoil3d/             # メインパッケージ
    ├── models.py        # データ構造の定義
    ├── config.py        # 設定管理 (YAML/対話モード)
    ├── solver.py        # XFOIL 実行・結果解析
    ├── physics.py       # 物理計算・RBF補間
    ├── plotting.py      # Plotly による可視化
    ├── validators.py    # パラメータバリデーション
    └── core.py          # 全体の実行制御ロジック
```

## 必要環境

| ツール | バージョン | 備考 |
|--------|------------|------|
| Python | 3.9 以上   |      |
| XFOIL  | 6.99       | `xfoil.exe` をプロジェクト直下に配置してください |

## インストール方法

1.  **リポジトリをクローン**:
    ```bash
    git clone https://github.com/your-repo/xfoil-3d.git
    cd xfoil-3d
    ```

2.  **依存ライブラリのインストール**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **XFOILの配置**:
    [XFOIL公式サイト](https://web.mit.edu/drela/Public/web/xfoil/)などから `xfoil.exe` を入手し、本ディレクトリ直下に配置する。

## 使用方法

### 1. 対話モードでの実行
スクリプトをそのまま実行すると、パラメータを一つずつ入力する対話モードが始まる。
```bash
python xfoil_3d.py
```

### 2. 設定ファイルを指定して実行
あらかじめ作成した `config.yaml` を指定して、前回の設定をデフォルト値として読み込む。
```bash
python xfoil_3d.py --config config.yaml
```

### 3. 設定ファイル (`config.yaml`) の内容
以下のような形式で計算条件を指定する。

| キー | 説明 |
|------|------|
| `dat_file` | 使用する翼型ファイル（`.dat`）のパス |
| `re_range` | `[最小Re, 最大Re, ステップ幅]` |
| `alpha_range` | `[最小迎角, 最大迎角, ステップ幅]` |
| `ncrit` | N-crit 値（遷移判定パラメータ） |
| `xfoil_exe` | XFOIL実行ファイルのパス |
| `show_scatter` | 3Dグラフに生データの計算点を表示するか（`true`/`false`） |

## 出力ファイル
実行後、以下のファイルが `results/[翼型名]/` ディレクトリに生成される（`[翼型名]` の部分は入力したファイル名）。

- `[翼型名]_polar_raw.csv`: XFOILでの計算生データ。
- `[翼型名]_polar_interp.csv`: 補間後のグリッドデータ。
- `[翼型名]_polar_3d.html`: 可視化レポート（ブラウザで閲覧可能）。
