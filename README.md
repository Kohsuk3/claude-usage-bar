# claude-usage-bar

Claude (Claude Code / Desktop) のセッション利用量を macOS のメニューバーに常時表示する小さな常駐アプリ。

- **リングゲージ** … 現在のセッション(5時間)使用率を円グラフで表示。緑 → 橙(70%) → 赤(90%) と色が変わる
- **テキスト** … `セッション% · 週間%` を併記
- **クリックで詳細** … セッション / 週間それぞれの使用率と、次回リセットの日時を表示

メニューバー表示イメージ:

```
◔ 56% · 7%
```

クリックすると:

```
セッション(5時間): 56%
  リセット 今日 15:34
─────────────
週間(7日): 7%
  リセット 6/8(月) 14:30
─────────────
更新: 30秒前
今すぐ更新
終了
```

## 仕組み

Anthropic API の `messages` エンドポイントに最小リクエスト(`max_tokens: 1` の quota ping)を投げ、
レスポンスヘッダ `anthropic-ratelimit-unified-{5h,7d}-{utilization,reset}` を読む。
Claude Desktop の「使用量」画面と同じ仕組みなので値が一致する。

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

`~/Library/LaunchAgents/com.kohsuk3.claude-usage-bar.plist` を作成して読み込む。
`ProgramArguments` のパスは自分の環境に合わせて書き換えること。

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
    <true/>
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

# 停止
launchctl bootout gui/$(id -u)/com.kohsuk3.claude-usage-bar
```

`KeepAlive` が有効なので、完全に止めるときは `pkill` ではなく `launchctl bootout` を使うこと。

## 設定

`main.py` 冒頭の定数で調整できる。

| 定数 | 既定値 | 説明 |
| --- | --- | --- |
| `FETCH_SECONDS` | `120` | API を叩く間隔(秒) |
| `UI_TICK_SECONDS` | `30` | 表示を再描画する間隔(秒) |

## ライセンス

MIT
