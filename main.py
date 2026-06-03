"""Claude のセッション利用量を macOS メニューバーに常時表示する常駐アプリ。

グリフ: ツイン同心円リング(外周=5時間セッション/閾値色, 内周=週間/クレイ色)+ セッション%。
パネル: クリックで NSWindow + WKWebView のリッチなドロップダウン(panel.html)。

データ元:
  - セッション%/週間%/リセット → Anthropic API messages の quota ping レスポンスヘッダ
    anthropic-ratelimit-unified-{5h,7d}-{utilization,reset}
  - 7日推移/モデル別内訳 → ~/.claude/projects/**/*.jsonl の assistant 行を集計

認証: Keychain の OAuth アクセストークン("Claude Code-credentials")。
"""
import json
import math
import os
import threading
import plistlib
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.request
import urllib.error

import objc
from AppKit import (
    NSApplication, NSStatusBar, NSImage, NSBezierPath, NSColor, NSFont,
    NSWindow, NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSScreen, NSAttributedString, NSForegroundColorAttributeName,
    NSFontAttributeName, NSImageLeft, NSVariableStatusItemLength,
    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorTransient,
    NSApplicationActivationPolicyAccessory, NSFloatingWindowLevel,
)
from Foundation import (
    NSObject, NSMakePoint, NSMakeSize, NSMakeRect, NSURL, NSTimer,
)
from AppKit import NSEvent, NSEventMaskLeftMouseDown, NSEventMaskRightMouseDown
from WebKit import (
    WKWebView, WKWebViewConfiguration, WKUserContentController,
)

FETCH_SECONDS = 120
KEYCHAIN_SERVICE = "Claude Code-credentials"
LAUNCH_LABEL = "com.kohsuk3.claude-usage-bar"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"
API_URL = "https://api.anthropic.com/v1/messages"
PING_MODEL = "claude-haiku-4-5-20251001"
SYSTEM_PROMPT = "You are Claude Code, Anthropic's official CLI for Claude."
PROJECTS_DIR = Path.home() / ".claude" / "projects"

ORANGE = "#D97757"
ORANGE_DEEP = "#C2613F"
AMBER = "#E0922F"
RED = "#D24B38"
CLAY_SOFT = "#E6A88B"


def _resource(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


# ---------- autostart ----------

def _autostart_enabled():
    return PLIST_PATH.exists()


def _set_autostart(enabled):
    uid = os.getuid()
    if enabled:
        if getattr(sys, "frozen", False):
            program_args = [sys.executable]
            workdir = str(Path(sys.executable).resolve().parent)
        else:
            program_args = [sys.executable, str(Path(__file__).resolve())]
            workdir = str(Path(__file__).resolve().parent)
        plist = {
            "Label": LAUNCH_LABEL,
            "ProgramArguments": program_args,
            "WorkingDirectory": workdir,
            "RunAtLoad": True,
            "KeepAlive": False,
            "StandardOutPath": "/tmp/claude-usage-bar.log",
            "StandardErrorPath": "/tmp/claude-usage-bar.log",
        }
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PLIST_PATH, "wb") as f:
            plistlib.dump(plist, f)
        subprocess.run(["launchctl", "enable", f"gui/{uid}/{LAUNCH_LABEL}"],
                       capture_output=True)
    else:
        subprocess.run(["launchctl", "disable", f"gui/{uid}/{LAUNCH_LABEL}"],
                       capture_output=True)
        try:
            PLIST_PATH.unlink()
        except FileNotFoundError:
            pass


# ---------- API quota ----------

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


# ---------- jsonl 集計 ----------

def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{round(n / 1000)}k"
    return str(int(n))


def _model_bucket(model):
    m = (model or "").lower()
    if "opus" in m:
        return ("Opus", ORANGE_DEEP, 0)
    if "sonnet" in m:
        return ("Sonnet", ORANGE, 1)
    if "haiku" in m:
        return ("Haiku", CLAY_SOFT, 2)
    return (None, None, 9)


def _aggregate_jsonl():
    """直近7日の (日別出力トークン, モデル別出力トークン) を集計。"""
    now = datetime.now()
    today = now.date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    by_day = {d: 0 for d in days}
    by_model = {}  # name -> [tokens, color, order]
    cutoff = now - timedelta(days=8)

    if not PROJECTS_DIR.exists():
        return by_day, days, by_model

    for jf in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            if datetime.fromtimestamp(jf.stat().st_mtime) < cutoff:
                continue
        except OSError:
            continue
        try:
            with open(jf, "r", errors="ignore") as fh:
                for line in fh:
                    if '"assistant"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("type") != "assistant":
                        continue
                    msg = d.get("message", {})
                    usage = msg.get("usage") or {}
                    out = usage.get("output_tokens", 0) or 0
                    if not out:
                        continue
                    ts = d.get("timestamp")
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                    except ValueError:
                        continue
                    dd = dt.date()
                    if dd in by_day:
                        by_day[dd] += out
                    name, color, order = _model_bucket(msg.get("model"))
                    if name:
                        if name not in by_model:
                            by_model[name] = [0, color, order]
                        by_model[name][0] += out
        except OSError:
            continue
    return by_day, days, by_model


def _build_panel_data(five, seven, error, autostart):
    sp = _pct(five) or 0
    wp = _pct(seven) or 0
    session_reset = _fmt_reset_time(five.get("resets_at")) if five else "不明"
    week_reset = _fmt_reset_time(seven.get("resets_at")) if seven else "不明"

    by_day, days, by_model = _aggregate_jsonl()
    wd = "月火水木金土日"
    max_day = max(by_day.values()) or 1
    trend = [{
        "v": round(by_day[d] / max_day * 100),
        "day": wd[d.weekday()],
        "date": f"{d.month}/{d.day}",
        "tok": _fmt_tokens(by_day[d]),
    } for d in days]

    total = sum(v[0] for v in by_model.values()) or 1
    models = []
    for name, (tok, color, order) in sorted(by_model.items(), key=lambda kv: kv[1][2]):
        models.append({
            "n": name, "v": round(tok / total * 100),
            "tok": _fmt_tokens(tok), "c": color,
        })
    if not models:
        models = [{"n": "—", "v": 0, "tok": "0", "c": CLAY_SOFT}]

    return {
        "session": sp, "week": wp,
        "reset": session_reset if not error else f"⚠️ {error}",
        "weekReset": week_reset,
        "trend": trend, "models": models,
        "autostart": bool(autostart),
        "appearance": "dark" if _is_dark() else "light",
    }


# ---------- glyph ----------

def _is_dark():
    try:
        style = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        return style == "Dark"
    except Exception:
        return True


def _hex_color(h, alpha=1.0):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


def _session_color(pct):
    if pct >= 90:
        return RED
    if pct >= 70:
        return AMBER
    return ORANGE


def _twin_ring_image(session, week, dark):
    """外周=セッション(閾値色), 内周=週間(クレイ)のツイン同心円リング。"""
    size = 22.0
    img = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    img.lockFocus()
    center = NSMakePoint(size / 2.0, size / 2.0)
    track = (NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.22) if dark
             else NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.16))

    def ring(radius, line_w, frac, color):
        bg = NSBezierPath.bezierPath()
        bg.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            center, radius, 0.0, 360.0)
        bg.setLineWidth_(line_w)
        track.setStroke()
        bg.stroke()
        if frac and frac > 0:
            fg = NSBezierPath.bezierPath()
            fg.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                center, radius, 90.0, 90.0 - 360.0 * min(frac, 1.0), True)
            fg.setLineWidth_(line_w)
            fg.setLineCapStyle_(1)
            color.setStroke()
            fg.stroke()

    ring(9.0, 3.0, session / 100.0, _hex_color(_session_color(session)))
    ring(4.8, 3.0, week / 100.0, _hex_color(CLAY_SOFT))
    img.unlockFocus()
    img.setTemplate_(False)
    return img


def _session_title(session, dark):
    color = (NSColor.colorWithCalibratedWhite_alpha_(0.97, 1.0) if dark
             else NSColor.colorWithCalibratedWhite_alpha_(0.15, 1.0))
    font = NSFont.monospacedDigitSystemFontOfSize_weight_(13.0, 0.4)
    return NSAttributedString.alloc().initWithString_attributes_(
        f" {session}%", {
            NSForegroundColorAttributeName: color,
            NSFontAttributeName: font,
        })


# ---------- app ----------

class PanelWindow(NSWindow):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True

class AppDelegate(NSObject):
    def init(self):
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.five = None
        self.seven = None
        self.error = None
        self.loaded = False
        self.pending = None
        self.refreshing = False
        return self

    def setup(self):
        bar = NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        btn = self.item.button()
        btn.setImagePosition_(NSImageLeft)
        btn.setTarget_(self)
        btn.setAction_("toggle:")

        self._build_panel()
        self.fetch()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            FETCH_SECONDS, self, "tick:", None, True)

    # ----- panel window + webview -----
    def _build_panel(self):
        cfg = WKWebViewConfiguration.alloc().init()
        ucc = WKUserContentController.alloc().init()
        ucc.addScriptMessageHandler_name_(self, "bridge")
        cfg.setUserContentController_(ucc)

        rect = NSMakeRect(0, 0, 344, 520)
        self.web = WKWebView.alloc().initWithFrame_configuration_(rect, cfg)
        self.web.setNavigationDelegate_(self)
        try:
            self.web.setValue_forKey_(False, "drawsBackground")
        except Exception:
            pass

        self.win = PanelWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(NSColor.clearColor())
        self.win.setHasShadow_(False)
        self.win.setLevel_(NSFloatingWindowLevel)
        self.win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces |
            NSWindowCollectionBehaviorTransient)
        self.win.setContentView_(self.web)
        self.win.setDelegate_(self)
        self.win.setAcceptsMouseMovedEvents_(True)
        self.win.setIgnoresMouseEvents_(False)

        html = _resource("panel.html").read_text(encoding="utf-8")
        self.web.loadHTMLString_baseURL_(html, NSURL.URLWithString_("about:blank"))

    def _push(self):
        if self.five is None and self.error:
            data = {
                "session": 0, "week": 0, "reset": f"⚠️ {self.error}",
                "weekReset": "Claude Code でログイン確認してね",
                "trend": [{"v": 0, "day": "月火水木金土日"[i]} for i in range(7)],
                "models": [{"n": "—", "v": 0, "tok": "0", "c": CLAY_SOFT}],
                "autostart": _autostart_enabled(),
                "appearance": "dark" if _is_dark() else "light",
            }
        else:
            data = _build_panel_data(self.five, self.seven, self.error,
                                     _autostart_enabled())
        js = "update(%s)" % json.dumps(json.dumps(data, ensure_ascii=False))
        if self.loaded:
            self.web.evaluateJavaScript_completionHandler_(js, self._after_render)
        else:
            self.pending = js

    def _after_render(self, result, err):
        self.web.evaluateJavaScript_completionHandler_(
            "contentHeight()", self._resize_to)

    def _resize_to(self, height, err):
        try:
            h = float(height)
        except (TypeError, ValueError):
            return
        # body padding: 10(top) + 30(bottom) を加える
        total = h + 40.0
        frame = self.win.frame()
        new = NSMakeRect(frame.origin.x, frame.origin.y, 344, total)
        self.win.setFrame_display_(new, True)
        if self.win.isVisible():
            self._reposition()

    # ----- WKNavigationDelegate -----
    def webView_didFinishNavigation_(self, web, nav):
        self.loaded = True
        if self.pending:
            js, self.pending = self.pending, None
            self.web.evaluateJavaScript_completionHandler_(js, self._after_render)

    # ----- WKScriptMessageHandler -----
    def userContentController_didReceiveScriptMessage_(self, ucc, message):
        self.handle_action(str(message.body()))

    def handle_action(self, name):
        if name == "refresh":
            self.manual_refresh()
        elif name == "open":
            subprocess.Popen(["open", "-a", "Claude"],
                             stderr=subprocess.DEVNULL) \
                if subprocess.run(["open", "-Ra", "Claude"],
                                  capture_output=True).returncode == 0 \
                else subprocess.Popen(["open", "https://claude.ai"])
            self.win.orderOut_(None)
        elif name in ("autostart",):
            _set_autostart(not _autostart_enabled())
            self._push()
        elif name == "settings":
            pass
        elif name == "quit":
            NSApplication.sharedApplication().terminate_(None)

    # ----- window toggle -----
    def toggle_(self, sender):
        if self.win.isVisible():
            self._hide()
        else:
            self._reposition()
            self.win.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self._outside_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown,
                lambda ev: self._hide())

    def _hide(self):
        mon = getattr(self, "_outside_monitor", None)
        if mon is not None:
            NSEvent.removeMonitor_(mon)
            self._outside_monitor = None
        self.win.orderOut_(None)

    def _reposition(self):
        btn = self.item.button()
        bframe = btn.window().convertRectToScreen_(btn.frame())
        wframe = self.win.frame()
        x = bframe.origin.x + bframe.size.width / 2.0 - wframe.size.width / 2.0
        y = bframe.origin.y - wframe.size.height + 6.0
        screen = NSScreen.mainScreen().visibleFrame()
        x = max(screen.origin.x + 4,
                min(x, screen.origin.x + screen.size.width - wframe.size.width - 4))
        self.win.setFrameOrigin_(NSMakePoint(x, y))

    def windowDidResignKey_(self, note):
        self._hide()

    # ----- data -----
    def manual_refresh(self):
        if self.refreshing:
            return
        self.refreshing = True
        if self.loaded:
            self.web.evaluateJavaScript_completionHandler_("setRefreshing(true)", None)
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        self._rr = _fetch_usage()
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "refreshDone:", None, False)

    def refreshDone_(self, _):
        five, seven, error = self._rr
        self.error = error
        if error is None:
            self.five, self.seven = five, seven
        self.refreshing = False
        self.render()
        if self.loaded:
            self.web.evaluateJavaScript_completionHandler_("flashRefreshed()", None)

    def tick_(self, timer):
        self.fetch()

    def fetch(self):
        five, seven, error = _fetch_usage()
        self.error = error
        if error is None:
            self.five, self.seven = five, seven
        self.render()

    def render(self):
        dark = _is_dark()
        sp = _pct(self.five)
        if sp is None and self.error:
            self.item.button().setImage_(None)
            self.item.button().setAttributedTitle_(
                NSAttributedString.alloc().initWithString_("⚠️"))
        else:
            sp = sp or 0
            wp = _pct(self.seven) or 0
            self.item.button().setImage_(_twin_ring_image(sp, wp, dark))
            self.item.button().setAttributedTitle_(_session_title(sp, dark))
        self._push()


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    delegate.setup()
    app.run()


if __name__ == "__main__":
    main()
