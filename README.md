# claude-usage-bar

Claude (Claude Code / Desktop) のセッション利用量を macOS のメニューバーに常時表示する小さな常駐アプリ。

- **ツイン同心円リング** … 外周=セッション(5時間)使用率、内周=週間(7日)使用率。外周は橙 → 琥珀(70%) → 赤(90%) と色が変わる
- **セッション%テキスト** … リングの隣に現在のセッション使用率を併記
- **クリックでリッチなパネル** … 大きなリング、今週メーター、直近7日の出力トークン推移グラフ(ホバーで詳細)、モデル別(Opus/Sonnet/Haiku)の内訳、クイックリンクをドロップダウン表示。ライト / ダーク両対応

パネルの内容:

- 5時間セッションの使用率リング + 次回リセット日時
- 今週の使用率メーター + リセット日時
- 直近7日の出力トークン推移(バーにホバーで「曜日 日付 · トークン数」を表示)
- モデル別の出力トークン内訳
- クイックリンク: Claudeを開く / 今すぐ更新 / ログイン時に起動(トグル) / 終了

パネル外をクリックすると自動で閉じる。「ログイン時に起動」のトグルでアプリから launchd の自動起動を ON/OFF できる(トグルしても起動中のアプリはそのまま動き続ける)。

## 仕組み

セッション% / 週間% / リセット日時は、Anthropic API の `messages` エンドポイントに最小リクエスト
(`max_tokens: 1` の quota ping)を投げ、レスポンスヘッダ
`anthropic-ratelimit-unified-{5h,7d}-{utilization,reset}` を読む。
Claude Desktop の「使用量」画面と同じ仕組みなので値が一致する。
7日推移とモデル別内訳は `~/.claude/projects/**/*.jsonl` の assistant 行(出力トークン)を集計している。

UI は pyobjc 直書き(NSStatusItem でグリフ描画 + ボーダーレス NSWindow に WKWebView でパネル描画)。

- 認証は Claude Code が Keychain に保存している OAuth アクセストークン (`Claude Code-credentials`) を利用。
  Claude Code を使っていれば自動でリフレッシュされるため、トークン管理は不要。
- デフォルト 2 分おきに取得。1 回あたり入力 ~22 + 出力 1 トークン程度で、レート上限への影響は無視できるレベル。
- トークンは実行時に Keychain から都度読むだけで、リポジトリには一切保存されない。

## 必要なもの

- macOS
- [uv](https://docs.astral.sh/uv/)
- Claude Code でログイン済みであること(Keychain に OAuth トークンがある状態)

## セットアップ

```bash
git clone https://github.com/Kohsuk3/claude-usage-bar.git
cd claude-usage-bar
uv sync
uv run python main.py
```

メニューバーにリングゲージが出れば成功。

## ログイン時に自動起動 (launchd)

一番手軽なのはメニューの「ログイン時に起動」を ON にするだけ。
クリックすると `~/Library/LaunchAgents/com.kohsuk3.claude-usage-bar.plist` が
自動生成・登録される(パスは実行中の Python / スクリプトから自動で埋まる)。

手動で管理したい場合は以下の plist を置く。`ProgramArguments` のパスは環境に合わせて書き換えること。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kohsuk3.claude-usage-bar</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/claude-usage-bar/.venv/bin/python3</string>
        <string>/path/to/claude-usage-bar/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/claude-usage-bar</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/claude-usage-bar.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/claude-usage-bar.log</string>
</dict>
</plist>
```

```bash
# 起動 (ログイン時に自動起動 + クラッシュ時に自動復活)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kohsuk3.claude-usage-bar.plist

# 停止(そのセッション限り)
launchctl bootout gui/$(id -u)/com.kohsuk3.claude-usage-bar
```

自動起動を恒久的に止めるならメニューの「ログイン時に起動」を OFF にするか、plist を削除する。

## .app としてビルド / 配布

PyInstaller で自己完結の `.app` を生成できる。uv の Python(static build)は
PyInstaller と相性が悪いため、ビルドは Python 3.12 の別 venv で行う。

```bash
uv venv --python 3.12 .venv-build
uv pip install --python .venv-build/bin/python \
  pyobjc-framework-webkit pyobjc-framework-quartz pyinstaller
.venv-build/bin/pyinstaller --noconfirm "Claude Usage Bar.spec"
# → dist/Claude Usage Bar.app
```

`Claude Usage Bar.spec` の `datas` に `panel.html` を含めてあるので、パネルの HTML もバンドルされる。

`Claude Usage Bar.spec` に `LSUIElement` 等を組み込んであるので、メニューバー常駐(Dock非表示)のアプリになる。`dist/Claude Usage Bar.app` を `/Applications` に移して使う。

### 配布時の注意

- **Claude Code ログイン済みの Mac でしか動かない**（Keychain の `Claude Code-credentials` を読むため）。
- **未署名なので他人の Mac では Gatekeeper にブロックされる**。初回は右クリック → 「開く」で起動するか、隔離属性を外す：
  ```bash
  xattr -dr com.apple.quarantine "Claude Usage Bar.app"
  ```
  正式な配布には Apple Developer 登録($99/年)による署名 + 公証が必要。

ビルド済みの zip は [Releases](https://github.com/Kohsuk3/claude-usage-bar/releases) からも取得できる。

## 設定

`main.py` 冒頭の定数で調整できる。

| 定数 | 既定値 | 説明 |
| --- | --- | --- |
| `FETCH_SECONDS` | `120` | API を叩く間隔(秒) |

## ライセンス

MIT
