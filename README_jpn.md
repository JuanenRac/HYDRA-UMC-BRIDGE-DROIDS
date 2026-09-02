<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - レッグ型・ヒューマノイド型ドロイド双方向連携ブリッジ
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-BRIDGE-DROIDS バナー" width="100%">
</p>

# 🤖 HYDRA-UMC-BRIDGE-DROIDS

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | 🇯🇵 <b>日本語</b></p>

### 🔗 HYDRA-UMCとレッグ型・ヒューマノイド型ドロイドとの間の依存関係なし連携境界

<p align="left">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Safety-Fails%20Closed-red.svg" alt="フェイルセーフ">
</p>

---

## 1. 🛠️ 技術概要

**HYDRA-UMC-BRIDGE-DROIDS** は、HYDRA-UMCとレッグ型またはヒューマノイド型のドロイドプラットフォームとの間の双方向・高レベルの連携境界であり、Wi-Fi、Bluetooth、またはセルラー(4G/5G)リンク経由で到達可能である。歩容、バランス、関節軌道を計算することは一切なく、それぞれが独自の実在する必須パラメータ契約を持つ、小規模で命名された全身アクション・トリガーの語彙(`WALK_TO`、`PICK_OBJECT`、`PLACE_OBJECT`、`RETURN_HOME`、`HOLD_POSITION`)を検証・転送するのみである。モーター制御ノードではなく、HYDRA-UMC-SERVER、MCUの限界、ウォッチドッグ、E-STOPを迂回することはできない。

`HYDRA-UMC-BRIDGE-AMR` および `HYDRA-UMC-BRIDGE-UAV` とともに **Mobile & Autonomous Bridges** ファミリーに属し、静的な **External Automation Bridges**(CNC、LASER、OPENPNP、PRINTER3D、ROS2)と同じ `HYDRA-UMC-SDK` のジョブ・安全契約を共有している —— つまりモバイルであれ静的であれ、いずれのブリッジも独自の「作業に安全」という定義を勝手に作ることはない。

### 主な機能:
* ✅ **実在する依存関係なしの連携コア:** `coordinator.py` の `DroidCoordinator` はトランスポートのインポートが一切ない(socketもベンダーSDKもなし)—— 意図的に純粋なPythonであり、実際のドロイドが接続されていないどのホストでもテスト可能である。*(実装済み、`tests/test_coordinator.py` でテスト済み)*
* ✅ **実在する命名済みアクション・トリガー語彙:** `WALK_TO`、`PICK_OBJECT`、`PLACE_OBJECT`、`RETURN_HOME`、`HOLD_POSITION` —— 生の関節コマンドは決して扱わない。全身の歩容、バランス、関節レベルの制御は、ドロイド自身の車載権限(Jetsonクラスまたは同等品)に留まる。*(実装済み)*
* ✅ **実在するアクションごとのパラメータ検証:** 各アクション・トリガーは、ジョブが転送される前にチェックされる独自の実在する最小限の必須パラメータ契約を持つ(例:`WALK_TO` は `x`/`y` を必要とする)—— 自身のアクションが必要とするものが欠けたリクエストはローカルで拒否され、下流に黙って通過することはない。*(実装済み、テスト済み)*
* ✅ **実在する共有安全ゲート:** `DroidCoordinator.dispatch()` を通じて送信されるすべてのジョブは、`HYDRA-UMC-SDK` の `bridge_contract` にある `evaluate_job()` によって評価される。これは他のすべての兄弟ブリッジとHYDRA-UMC-SERVERが使うのと同じゲートである。生産フェーズには外部機械が `IDLE` であり、HYDRA-UMCセルが `READY` であることが必要だが、(`ABORT` からマッピングされる)`HOLD_POSITION` は故障中でも要求可能なままである。*(実装済み)*
* ✅ **フェイルクローズのフェーズルーティングと静的エビデンス:** 未知の将来SDKフェーズは、推測されるのではなく拒否される。`inspect_action_plan.py` はトランスポートを一切開かずに静的スキーマ `1.0` のアクションプランを出力する。*(実装・テスト済み)*
* ✅ **実際の Boston Dynamics Spot トランスポート:** `spot_transport.py` の `SpotDroidControl` は、すでにゲートを通過したディスパッチを、実際の bosdyn-client コマンド（`synchro_stand_command`/`synchro_sit_command`/`synchro_trajectory_command_in_body_frame`、`RobotCommandClient.robot_command()` 経由で送信）として送信する —— 拒否されたディスパッチがネットワークに届くことは決してない。*(実装済み、`tests/test_spot_transport.py` でテスト済み)*
* ✅ **非破壊的なビルド/テスト:** `build-test.bat`/`.sh` はソースをコンパイルし、バージョンやCHANGELOGを変更せずに決定論的なユニットテストを実行する。*(実装済み、下記「ビルドと実行」を参照)*
* 🔜 **Spot 以外のドロイドプラットフォーム向けの Wi-Fi/BT/4G-5G アダプター** —— そのプラットフォームが選定・テストされた後にのみ導入される。*(計画中)*

---

## 2. 🔄 ドロイド連携フロー

```mermaid
flowchart LR
    DROID["レッグ型 / ヒューマノイド型ドロイド<br/>(Wi-Fi / BT / 4G-5G)"] -- "アクショントリガー" --> BRIDGE["BRIDGE-DROIDS<br/>DroidCoordinator.dispatch()"]
    BRIDGE -- BridgeJob --> SDK["HYDRA-UMC-SDK<br/>evaluate_job()"]
    SDK -- GateDecision --> SERVER["HYDRA-UMC-SERVER"]
    SERVER -- "ジョブ / 中止" --> MCU["MCU安全"]
```

---

## 3. 🧱 アーキテクチャと設計判断

* **なぜコアは歩容やバランスを一切計算しないのか。** ドロイド自身の車載コンピュート(Jetsonクラスまたは同等品)は、すでに実在するハードウェア固有の全身コントローラーを実行している —— これをここで再導出することは、それを不出来に複製するか、それと衝突するかのいずれかになる。命名された目的地/アクション・トリガー(`WALK_TO x y`、`PICK_OBJECT object_id`)のみを送信することで、HYDRA-UMCの役割は連携にとどまる。これは本プロジェクトが出発点とした貼り付けられたアーキテクチャノート「コア内でドロイドの歩容を計算しないこと」と一致する。
* **なぜ各アクション・トリガーは独自の明示的な必須パラメータリストを持つのか。** `x`/`y` のない `WALK_TO`、あるいは `object_id` のない `PICK_OBJECT` は、実在する検出可能なリクエスト形式のエラーである —— トランスポートに至る前にここで拒否することは、不完全な指示を転送してドロイド自身のファームウェアも安全に拒否することを期待するよりも、明確に優れている。
* **なぜ `DroidCoordinator.dispatch()` はそれでも共有の `evaluate_job()` ゲートを通してすべてのジョブを流すのか。** ドロイドは、CNC、LASER、OPENPNP、PRINTER3D、ROS2が使うのと同じ `bridge_contract` の単なる別のクライアントに過ぎない —— 他のすべてのブリッジやHYDRA-UMC-SERVERが強制するIDLE/READYロジックを特別に迂回することはない。
* **なぜ(`ABORT` からの)`HOLD_POSITION` は故障中でも要求可能なままなのか。** ゲートの生産フェーズ要件(`IDLE` + `READY`)は、中止リクエストには意図的に同じ方法で適用されない —— オペレーターは、それまで行っていたことを続けるのではなく、故障の最中であってもドロイドにその場で静止するよう常に要求できなければならない。
* **なぜトランスポートアダプターと具体的なコマンドインターフェースがまだこのリポジトリにないのか。** 特定のドロイドプラットフォームの実際のWi-Fi/BT/4G-5Gコマンドプロトコルに、それが選定・テストされる前にコミットすることは、この依存関係のないローカルコアが検証できない前提を組み込むリスクを伴う。
* **エコシステムの他部分とどう関係するか。** BRIDGE-DROIDSは実際のドロイドと `HYDRA-UMC-SDK` → `HYDRA-UMC-SERVER` → MCU安全との間に位置する —— 連携境界であり、モーター制御ノードでは決してなく、HYDRA-UMC-SERVER、MCUの限界、ウォッチドッグ、E-STOPを迂回することはできない。

---

## 📂 ディレクトリ構成

```text
HYDRA-UMC-BRIDGE-DROIDS/
├── src/
│   └── hydra_umc_bridge_droids/
│       ├── __init__.py
│       └── coordinator.py       # DroidCoordinator: 依存関係なしのアクショントリガーゲート
├── tests/
│   └── test_coordinator.py      # 連携コアの決定論的ユニットテスト
├── tools/
│   ├── build_test.py            # 非破壊的なコンパイル+テストランナー (build-test.bat/.sh)
│   ├── bump_version.py          # pyproject.toml、マニフェスト、CHANGELOG.md を同期
│   └── inspect_action_plan.py   # 静的なアクションプランを出力する(トランスポートを開かない)
├── docs/
│   └── BRIDGE_GUIDE.md          # 適用範囲、対応プラットフォーム、スクリプト、ハードウェア受け入れゲート
├── build-test.bat / build-test.sh  # 検証のみ、リポジトリを一切変更しない
├── build.bat / build.sh            # 検証後、成功時のみバージョン + CHANGELOG を更新
├── pyproject.toml               # パッケージメタデータ。HYDRA-UMC-SDK に依存 (git)
├── hydra-umc.project.json       # エコシステムマニフェスト(バージョン、成熟度、ファミリー)
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md / CONTRIBUTING.md / SECURITY.md / SUPPORT.md
├── LICENSE / LICENSE.md
└── README.md / README_*.md      # 本ファイルおよびその6言語訳
```

---

## 4. ⚙️ ビルドと実行

Python 3.11以上が必要。`tools/build_test.py` は `HYDRA-UMC-SDK` が兄弟ディレクトリ(`../HYDRA-UMC-SDK`)としてチェックアウトされているか、環境変数 `HYDRA_UMC_SDK_ROOT` で指定されていることを期待する。

```bash
# Windows
build-test.bat      # 検証のみ —— バージョン/CHANGELOGの変更なし
build.bat            # 検証後、成功時にバージョン + CHANGELOG を更新

# Linux/macOS
bash build-test.sh
bash build.sh
```

`build-test` は `src/` 配下の各モジュールを `py_compile` でコンパイルし、`unittest` の全スイート(`tests/test_coordinator.py`)を実行する —— 実際のドロイド接続もネットワークもなく決定論的に動作し、バージョンやCHANGELOGを変更しない。`build` はまず同じ検証を実行し、成功した場合のみ `tools/bump_version.py` を呼び出して `pyproject.toml`、`hydra-umc.project.json`、`CHANGELOG.md` の間でバージョンを同期する。実際のハードウェア向け `run` コマンドはまだ存在しない —— それには検証済みのトランスポートアダプターと実際のドロイドプラットフォームが必要である。

---

## ✅ 現状と次のステップ

**現時点で実在するもの:** バージョン `0.0.4`。実在するアクションごとのパラメータ検証、フェイルクローズのフェーズルーティング、静的な `plan-only` アクションスキーマ、実際の bosdyn-client コマンドを送信する実際の Boston Dynamics Spot トランスポート(`SpotDroidControl`)、SDKチェックアウトを伴いCIに組み込まれた非破壊的なbuild-testスクリプトを備える依存関係なしの連携コア(`DroidCoordinator`)として機能している。

**統合境界:** このブリッジは連携境界に過ぎない —— モーター制御ノードではなく、HYDRA-UMC-SERVER、MCUの限界、ウォッチドッグ、E-STOPを迂回することはできない。送信されるすべてのジョブは、依然としてすべての兄弟ブリッジが使う同じ共有ゲートを通過する。

**今後の課題:** 実際のトランスポート(Wi-Fi/BT/4G-5G)も物理的なドロイドもまだ一切検証されていない —— 実際のトランスポートアダプターと文書化されたドロイドコマンドインターフェースは、具体的なプラットフォームが選定・テストされた後にのみ導入される。

---

## 🔗 関連プロジェクト

本プロジェクトは、同じ著者(JuanenRac / Electro Hobby 3D)によるより大きなロボティクス・エコシステムの一部であり、ファームウェア、制御ソフトウェア、AIノード、フリート管理ツールにまたがる。リクエストが実際には本リポジトリではなくこれらのいずれかに関するものである可能性があるため、知っておく価値がある。

### 直接関連

- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** —— このブリッジ(および他のすべてのブリッジ)がジョブを評価する共有のジョブ・安全契約。
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** —— このブリッジが報告する認証済みエコシステム境界。
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** —— AGV/AMRフリート向けの兄弟モバイルブリッジ。
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** —— ドローン向けの兄弟モバイルブリッジ。

### エコシステムのその他

**HYDRA-UMCプラットフォーム** —— このブリッジが補助機能を調整するマルチロボット・マイクロファクトリー
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** —— 最大8本のロボットアームを統括するCM5 + STM32H745マザーボード。
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** —— すべての制御クライアントとブリッジが通信するExpress/WebSocketバックエンド。
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** —— Webベースの制御ダッシュボード、マルチロボット3D可視化。

**External Automation Bridges** —— 同じ `HYDRA-UMC-SDK` ジョブゲートを共有する兄弟リポジトリ群
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** —— CNCセル連携ブリッジ。
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** —— レーザーセル連携ブリッジ。
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** —— OpenPnP向けボードフローブリッジ。
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** —— オープンな3Dプリントソフトウェア向け連携ブリッジ。
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** —— 任意のROS 2プラットフォーム向け汎用連携ブリッジ。

**安全・統合の実証**
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** —— ブリッジファミリー全体で使われるセルゾーンの安全実証。
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** —— ハードウェア・イン・ザ・ループのテスト実証。

## 👤 作者
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 ライセンス
GPL-3.0 - 詳細はLICENSEを参照。
