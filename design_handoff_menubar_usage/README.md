# Handoff: Claude 使用量 メニューバーアプリ — Twin Rings グリフ＋ドロップダウンパネル

## Overview
macOS のメニューバー常駐アプリ。Claude の使用量を一目で伝える。
2つの指標を表示する:
- **5時間セッションの使用率**（主役）
- **週の使用率**（副）

メニューバーには小さな**ツイン・リング（同心円）グリフ**を置き、クリックで使用状況の詳細パネルがドロップダウンする。

## About the Design Files
このバンドルに含まれる `Menu Bar Explorations.html` は **HTML で作られたデザインリファレンス**です。意図した見た目と挙動を示すプロトタイプであり、そのまま製品コードとしてコピーするものではありません。

実装タスクは、これらのデザインを**ターゲットのコードベースの既存環境で再現すること**です。macOS メニューバーアプリなら **SwiftUI / AppKit（`NSStatusItem` + `NSPopover`、または MenuBarExtra）** が自然な選択。Electron/Tauri ベースなら HTML/CSS を流用しつつ、各環境の確立されたパターンに合わせてください。グリフは静的画像ではなく**ベクター（SVG / Core Graphics の描画）**で実装し、`@2x/@3x` のスケールとライト/ダーク両対応をすること。

## Fidelity
**High-fidelity (hifi)**。色・サイズ・余白・アニメーション・しきい値はすべて確定値。下記の数値どおりにピクセル単位で再現してください。ただし数値はベースの座標系（viewBox 16 など）で記述しているため、実機ではポイント単位へ等倍スケールします。

> 注：色は Anthropic / Claude のブランド由来のクレイ・オレンジを使用しています。社内に正式なブランドカラー定義があればそれを優先してください。

---

## Views

### View 1 — メニューバー・グリフ（Twin Rings）
**Purpose:** 常時表示。セッション残量を外周リング、週残量を内周リングで示す。クリックでパネルを開く。

**Layout:** 横並び（inline-flex, `align-items:center`, `gap: 0.36em`）。左にリング SVG、右にセッション％テキスト。グリフ全体の高さ＝メニューバーアイコン領域（実機で約 17pt 相当）。

**Geometry（SVG viewBox `0 0 16 16`）:**
| 要素 | cx,cy | r | stroke-width | 備考 |
|---|---|---|---|---|
| 外周トラック | 8,8 | 6.4 | 1.5 | 背景の溝 |
| 外周アーク（セッション） | 8,8 | 6.4 | 1.5 | 進捗。`stroke-linecap:round` |
| 内周トラック | 8,8 | 3.4 | 1.5 | 背景の溝 |
| 内周アーク（週） | 8,8 | 3.4 | 1.5 | 進捗。`stroke-linecap:round` |

- アークは **12時方向起点・時計回り**。SVG では `transform: rotate(-90 8 8)`、`pathLength="100"`、`stroke-dasharray="100"`、`stroke-dashoffset = 100 − percent` で表現（実機では `CGContext` の `addArc(startAngle: -90°)` 相当）。
- **トラック色:** ダーク背景 `rgba(255,255,255,0.22)` / ライト背景 `rgba(0,0,0,0.16)`。
- **外周アーク色:** セッション％の**しきい値で変化**（下記 Tokens 参照）。
- **内周アーク色:** 常に `--clay-soft #E6A88B`（週は主役を邪魔しないミュート色で固定）。

**テキスト:**
- 内容：セッション％のみ（例 `79%`）。週％はリングで表現するため非表示。
- フォント：SF Pro Text / `-apple-system`、サイズ ≈ グリフ高 × 0.78（17pt 時 ≈ 13pt）、**weight 600**、`font-variant-numeric: tabular-nums`、`letter-spacing: -0.01em`。
- 色：外周アークと同じしきい値色。

### View 2 — ドロップダウンパネル（2案）
クリックで開くポップオーバー。**A: 温かみ・ブランド（ダーク）** と **B: クリーン・ネイティブ（ライト）** の2バリアントを用意。中身は同一構造。**OS の外観に追従して A/B を自動選択する実装を推奨。**

**コンテナ:** 幅 `300px`、`border-radius: 16px`、上辺中央に 14×14 を 45° 回転した三角の**カレット（吹き出しの矢印）**。影 `0 30px 70px -24px rgba(0,0,0,.7)`。
- ダーク: bg `#262624`、border `rgba(255,255,255,.08)`、本文 `#ece8df`。
- ライト: bg `#faf9f5`、border `rgba(0,0,0,.07)`、本文 `#33312d`。

**構成（上から）:**
1. **ヘッダー** `padding:15px 16px 13px`、下罫線。スパークマーク（17px, 塗り `#D97757`）＋ `Claude 使用状況`（13.5px / weight 600）＋ 右端に歯車アイコン（opacity .5、hover .9）。
2. **ヒーロー行** `padding:16px`、`gap:16px`。左：**大リング** 74×74、r31 / sw6、round cap、12時起点時計回り、色＝セッションしきい値色、トラック `rgba(255,255,255,.12)`(dark)/`rgba(0,0,0,.09)`(light)。中央に `79%`（21px / weight600）＋ `セッション`（9px, opacity .5）。右：`5時間セッション`（12px/600）＋ 時計アイコン＋ `あと2時間14分でリセット`（12.5px, ミュート）。
3. **今週ブロック** ラベル `今週` ＋ 右に `61% · 月曜にリセット`。下に高さ7px / radius4 のメーター。`fill width = week%`、色＝**週％のしきい値色**。
4. **直近7日の推移** ラベル ＋ 右 `1日あたり`。7本の縦棒（`height = value×0.42+3 px`、`gap:5px`、コンテナ高 46px、`border-radius:3px`）。色 `rgba(217,119,87,.32)`、**最終日のみ** 実線オレンジ `#D97757`。下に曜日ラベル `月 火 水 木 金 土 日`（9px、最終日はオレンジ/600）。
5. **モデル別の内訳** ラベル ＋ 右 `トークン`。各行＝モデル名(width 62, 12px)＋トラック(height6, radius3)＋トークン値(11px, 右寄せ)。
6. **クイックリンク** 上に区切り線。各行 `padding:9px 16px`、13px、hover bg `rgba(217,119,87,.14)`。アイコン＋ラベル＋右端にショートカット。

---

## Interactions & Behavior
- **クリック**：グリフ → パネル開閉（`NSPopover` / MenuBarExtra）。
- **しきい値による色＆状態**（セッション％基準）:
  - `< 70%` → オレンジ `#D97757`（正常）
  - `70–89%` → アンバー `#E0922F`（警告）
  - `≥ 90%` → レッド `#D24B38`（上限間近）＋**鼓動アニメーション**
- **アニメーション（更新時）:**
  - リング充填：`stroke-dashoffset` を `0.9s cubic-bezier(0.22, 1, 0.36, 1)` でトランジション。色変化は `0.5s ease`。
  - 大リング・週メーター・推移バーも同じ充填トランジション。
  - **鼓動（上限間近のみ）:** opacity `1 ↔ 0.42`、`1.15s ease-in-out infinite`。
  - **`prefers-reduced-motion: reduce` で全アニメーション停止**（必須）。
- **ライト/ダーク**：メニューバー外観に追従。グリフのトラック色・テキストのミュート色、パネルの A/B を切り替える。

## State Management
必要な状態:
- `sessionPct: Int`（0–100、5時間セッション使用率）
- `weekPct: Int`（0–100、週使用率）
- `sessionResetAt: Date`（→ `あとN時間M分` を算出）
- `weekResetLabel`（例：`月曜にリセット`）
- `dailyHistory: [Int]`（直近7日、各日の使用率）
- `modelBreakdown: [(name, pct, tokens)]`
- `appearance: light | dark`（OS 追従）
- 派生：`level = sessionPct >= 90 ? .critical : sessionPct >= 70 ? .warning : .ok`

データ取得：使用量 API をポーリング（例：1〜5分間隔）し上記を更新 → グリフとパネルを再描画。

## Design Tokens
**Colors**
| Token | Hex | 用途 |
|---|---|---|
| `--orange` | `#D97757` | 正常 / プライマリ |
| `--orange-deep` | `#C2613F` | Opus バー等の濃色 |
| `--amber` | `#E0922F` | 警告（70–89%） |
| `--red` | `#D24B38` | 上限間近（≥90%） |
| `--clay-soft` | `#E6A88B` | 週リング（固定ミュート色） |
| panel dark bg | `#262624` | ダークパネル背景 |
| panel light bg | `#faf9f5` | ライトパネル背景 |
| text on dark | `#ece8df` | ダーク上の本文 |
| text dark dim | `rgba(236,232,223,.55)` | ダーク上の補助 |
| text on light | `#33312d` | ライト上の本文 |
| text light dim | `#8d8579` | ライト上の補助 |
| track (dark) | `rgba(255,255,255,.22)` | グリフ溝・ダーク |
| track (light) | `rgba(0,0,0,.16)` | グリフ溝・ライト |

**Typography**：SF Pro Text / `-apple-system`（メニューバー実機フォント）。本文 13px。タブラー数字必須（`tabular-nums`）。

**Spacing / Radius**：パネル radius 16px、メーター radius 4px、トラック radius 3px、パネル padding 16px、グリフ gap 0.36em。

**Easing**：充填 `cubic-bezier(0.22, 1, 0.36, 1)` / 0.9s、色 0.5s ease、鼓動 1.15s ease-in-out。

## Assets
- **スパークマーク**：4点星の SVG パス（`Menu Bar Explorations.html` 内 `SPARK` 定数を参照）。社内に正式な Claude/Anthropic ロゴ資産があればそちらを優先。
- システムアイコン（Wi-Fi / バッテリー / 時計 / 歯車）：実機では SF Symbols を使用。プロトタイプ内の SVG はプレースホルダ。
- 画像アセットなし。すべてベクター描画。

## Files
- `Menu Bar Explorations.html` — 全方向の探索ボード（採用は **C ツイン・リング**）。CSS と描画ロジックは末尾の `<script>` 内。グリフ生成は `build('twin', h)`、パネルは `panelHTML()` / `updatePanels()`、しきい値色は `colorFor()` を参照。
