"""Claude Code/Desktop のセッション利用量をmacOSメニューバーに常時表示する。

データ元: Anthropic API の messages エンドポイントに最小リクエスト(quota ping)を
投げ、レスポンスヘッダ anthropic-ratelimit-unified-{5h,7d}-{utilization,reset}
を読む。Claude Desktop の「使用量」画面と同じ仕組みなので値が一致する。

認証: Claude Code が Keychain に保存している OAuth アクセストークンを使う
("Claude Code-credentials")。Claude Code を使っていれば自動でリフレッシュされる。
"""
import json
import subprocess
import time
from datetime import datetime, timedelta
import urllib.request
import urllib.error

import rumps
from AppKit import NSImage, NSBezierPath, NSColor
from Foundation import NSMakePoint, NSMakeSize

FETCH_SECONDS = 120       # API を叩く間隔(秒)
UI_TICK_SECONDS = 30      # カウントダウン再描画の間隔(秒)
KEYCHAIN_SERVICE = "Claude Code-credentials"
API_URL = "https://api.anthropic.com/v1/messages"
PING_MODEL = "claude-haiku-4-5-20251001"
SYSTEM_PROMPT = "You are Claude Code, Anthropic's official CLI for Claude."


def _read_token():
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return json.loads(raw)["claudeAiOauth"]["accessToken"]
    except Exception:
        return None


def _fetch_usage():
    """API を叩いて (five, seven, error) を返す。

    five/seven は {"utilization": 0-1, "resets_at": unix秒} または None。
    error は文字列(認証切れ等) または None。
    """
    token = _read_token()
    if not token:
        return None, None, "トークン取得失敗"

    body = json.dumps({
        "model": PING_MODEL,
        "max_tokens": 1,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": "quota"}],
    }).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            headers = resp.headers
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None, None, "再ログインが必要"
        # 429(レート上限)でもヘッダは付いてくるので読み取りを試みる
        headers = e.headers
    except Exception:
        return None, None, "接続エラー"

    def window(prefix):
        u = headers.get(f"anthropic-ratelimit-unified-{prefix}-utilization")
        r = headers.get(f"anthropic-ratelimit-unified-{prefix}-reset")
        if u is None or r is None:
            return None
        try:
            return {"utilization": float(u), "resets_at": float(r)}
        except ValueError:
            return None

    return window("5h"), window("7d"), None


def _pct(window):
    if not window:
        return None
    return max(0, min(100, round(window["utilization"] * 100)))


def _fmt_reset_time(resets_at):
    if not isinstance(resets_at, (int, float)):
        return "不明"
    dt = datetime.fromtimestamp(resets_at)
    now = datetime.now()
    hm = dt.strftime("%H:%M")
    if dt.date() == now.date():
        return f"今日 {hm}"
    if dt.date() == (now + timedelta(days=1)).date():
        return f"明日 {hm}"
    weekday = "月火水木金土日"[dt.weekday()]
    return f"{dt.month}/{dt.day}({weekday}) {hm}"


def _gauge_color(pct):
    if pct >= 90:
        return NSColor.systemRedColor()
    if pct >= 70:
        return NSColor.systemOrangeColor()
    return NSColor.systemGreenColor()


def _gauge_image(pct):
    """使用率に応じて満ちるリングゲージの NSImage を描く。"""
    size = 18.0
    img = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    img.lockFocus()
    center = NSMakePoint(size / 2.0, size / 2.0)
    radius = size / 2.0 - 2.2
    line_w = 2.6

    bg = NSBezierPath.bezierPath()
    bg.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
        center, radius, 0.0, 360.0
    )
    bg.setLineWidth_(line_w)
    NSColor.colorWithCalibratedWhite_alpha_(0.55, 0.35).setStroke()
    bg.stroke()

    if pct and pct > 0:
        frac = min(pct, 100) / 100.0
        fg = NSBezierPath.bezierPath()
        # 真上(90度)から時計回りに frac 分だけ描く
        fg.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            center, radius, 90.0, 90.0 - 360.0 * frac, True
        )
        fg.setLineWidth_(line_w)
        fg.setLineCapStyle_(1)  # round
        _gauge_color(pct).setStroke()
        fg.stroke()

    img.unlockFocus()
    img.setTemplate_(False)
    return img


def _status_item(app):
    nsapp = getattr(app, "_nsapp", None)
    return getattr(nsapp, "nsstatusitem", None) if nsapp else None


class ClaudeUsageBar(rumps.App):
    def __init__(self):
        super().__init__("Claude", title="⚪️ Claude", quit_button=None)
        self.five = None
        self.seven = None
        self.error = None
        self.fetched_at = None

        self.session_item = rumps.MenuItem("セッション: -")
        self.session_reset = rumps.MenuItem("  -")
        self.week_item = rumps.MenuItem("週間: -")
        self.week_reset = rumps.MenuItem("  -")
        self.updated_item = rumps.MenuItem("更新: -")
        self.menu = [
            self.session_item,
            self.session_reset,
            None,
            self.week_item,
            self.week_reset,
            None,
            self.updated_item,
            rumps.MenuItem("今すぐ更新", callback=lambda _: self.fetch()),
            None,
            rumps.MenuItem("終了", callback=rumps.quit_application),
        ]
        self.fetch()

    @rumps.timer(FETCH_SECONDS)
    def _fetch_tick(self, _):
        self.fetch()

    @rumps.timer(UI_TICK_SECONDS)
    def _ui_tick(self, _):
        # API は叩かず、カウントダウンだけ再計算
        self.render()

    def fetch(self):
        five, seven, error = _fetch_usage()
        self.error = error
        if error is None:
            self.five, self.seven = five, seven
            self.fetched_at = time.time()
        self.render()

    def render(self):
        item = _status_item(self)
        if self.error and self.five is None:
            if item is not None:
                item.setImage_(None)
            self.title = "⚠️ Claude"
            self.session_item.title = f"エラー: {self.error}"
            self.session_reset.title = "  Claude Code でログインを確認してね"
            self.week_item.title = "週間: -"
            self.week_reset.title = "  -"
            self.updated_item.title = "更新: -"
            return

        sp = _pct(self.five)
        wp = _pct(self.seven)
        sp_txt = f"{sp}%" if sp is not None else "--"
        wp_txt = f"{wp}%" if wp is not None else "--"
        err_mark = " ⚠️" if self.error else ""
        if item is not None:
            item.setImage_(_gauge_image(sp if sp is not None else 0))
        self.title = f"{sp_txt} · {wp_txt}{err_mark}"

        self.session_item.title = f"セッション(5時間): {sp_txt}"
        self.session_reset.title = (
            f"  リセット {_fmt_reset_time(self.five.get('resets_at') if self.five else None)}"
        )
        self.week_item.title = f"週間(7日): {wp_txt}"
        self.week_reset.title = (
            f"  リセット {_fmt_reset_time(self.seven.get('resets_at') if self.seven else None)}"
        )

        if self.fetched_at:
            ago = int(time.time() - self.fetched_at)
            if ago < 60:
                ago_txt = f"{ago}秒前"
            elif ago < 3600:
                ago_txt = f"{ago // 60}分前"
            else:
                ago_txt = f"{ago // 3600}時間前"
            note = f"（取得失敗: {self.error}）" if self.error else ""
            self.updated_item.title = f"更新: {ago_txt}{note}"
        else:
            self.updated_item.title = "更新: -"


if __name__ == "__main__":
    ClaudeUsageBar().run()
