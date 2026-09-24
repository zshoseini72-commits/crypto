"""دیدبان سیگنال رمزارز - نسخه پایتون (Flet)
سازگار با Flet قدیمی (0.2x) و جدید (0.80+). فقط به خود flet نیاز دارد.
"""
import asyncio
import importlib
import inspect
import json
import math
import os
import struct
import sys
import time
import urllib.parse
import urllib.request
import wave

import flet as ft

# در Flet 1.0 دکمه ElevatedButton حذف و با Button جایگزین شده است.
Button = getattr(ft, "Button", None) or getattr(ft, "ElevatedButton")
OutlinedButton = getattr(ft, "OutlinedButton", None) or Button
TextButton = getattr(ft, "TextButton", None) or Button

API_BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
TIMEFRAMES = [("15m", "۱۵ دقیقه"), ("1h", "۱ ساعت"), ("4h", "۴ ساعت"), ("1d", "۱ روز")]
SIGNAL_TEXT = {"buy": "زمان خرید", "sell": "زمان فروش", "hold": "صبر کنید"}
COLORS = {"buy": "#0a8f6a", "sell": "#c8312f", "hold": "#8a94a0"}
MUTE = "#66727f"
LINE = "#d9dfe5"
FONT_URL = "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/fonts/ttf/Vazirmatn-Regular.ttf"
FETCH_ERRORS = (OSError, ValueError, KeyError, IndexError, TypeError)

STORAGE_DIR = os.getenv("FLET_APP_STORAGE_DATA") or os.path.join(
    os.path.expanduser("~"), ".signal_watch"
)
os.makedirs(STORAGE_DIR, exist_ok=True)
COINS_FILE = os.path.join(STORAGE_DIR, "coins.json")


# ------------------------------------------------------------ ذخیره‌سازی
def load_coins() -> list:
    try:
        with open(COINS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
    except FETCH_ERRORS:
        pass
    return list(DEFAULT_COINS)


def save_coins(coins: list) -> None:
    try:
        with open(COINS_FILE, "w", encoding="utf-8") as f:
            json.dump(coins, f)
    except OSError:
        pass


# ------------------------------------------------------------ دریافت داده
def fetch_klines(symbol: str, timeframe: str) -> list:
    for base in API_BASES:
        try:
            query = urllib.parse.urlencode(
                {"symbol": f"{symbol}USDT", "interval": timeframe, "limit": 250}
            )
            req = urllib.request.Request(
                f"{base}/api/v3/klines?{query}", headers={"User-Agent": "signal-watch"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, list) or len(data) < 120:
                raise ValueError("داده کافی دریافت نشد.")
            # آخرین کندل ممکن است هنوز باز باشد؛ حذفش می‌کنیم.
            return [
                {
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
                for k in data[:-1]
            ]
        except FETCH_ERRORS:
            continue
    raise RuntimeError(
        "دریافت داده ممکن نشد؛ اینترنت، دسترسی Binance یا نماد را بررسی کنید."
    )


# ------------------------------------------------------------ اندیکاتورها
def calculate_ema(values: list, period: int) -> list:
    n = len(values)
    if n == 0:
        return []
    if n < period:
        return [values[0]] * n
    out = [0.0] * n
    ema = sum(values[:period]) / period
    out[period - 1] = ema
    k = 2 / (period + 1)
    for i in range(period, n):
        ema = values[i] * k + ema * (1 - k)
        out[i] = ema
    for i in range(period - 1):
        out[i] = out[period - 1]
    return out


def calculate_rsi(values: list, period: int = 14) -> list:
    n = len(values)
    out = [50.0] * n
    if n <= period:
        return out
    gain = 0.0
    loss = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        if d > 0:
            gain += d
        else:
            loss -= d
    gain /= period
    loss /= period
    out[period] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    for i in range(period + 1, n):
        d = values[i] - values[i - 1]
        gain = (gain * (period - 1) + max(d, 0.0)) / period
        loss = (loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def midpoint(data: list, end: int, period: int) -> float:
    start = end - period + 1
    if start < 0:
        raise ValueError("داده کافی نیست.")
    window = data[start : end + 1]
    return (max(c["high"] for c in window) + min(c["low"] for c in window)) / 2


def analyze(data: list) -> dict:
    closes = [c["close"] for c in data]
    last = len(closes) - 1
    price = closes[last]

    # Ichimoku
    tenkan = midpoint(data, last, 9)
    kijun = midpoint(data, last, 26)
    past = last - 26
    ichi_vote = 0
    ichi_text = "داخل ابر/خنثی"
    if past >= 52:
        span_a = (midpoint(data, past, 9) + midpoint(data, past, 26)) / 2
        span_b = midpoint(data, past, 52)
        top = max(span_a, span_b)
        bottom = min(span_a, span_b)
        if price > top and tenkan > kijun:
            ichi_vote = 1
        elif price < bottom and tenkan < kijun:
            ichi_vote = -1
        ichi_text = (
            "بالای ابر" if ichi_vote > 0 else "زیر ابر" if ichi_vote < 0 else "داخل ابر/خنثی"
        )

    # MACD
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    macd = [a - b for a, b in zip(ema12, ema26)]
    signal_line = calculate_ema(macd, 9)
    hist = macd[last] - signal_line[last]
    macd_vote = 1 if hist > 0 else -1 if hist < 0 else 0

    # RSI
    rsi = calculate_rsi(closes, 14)[last]
    rsi_vote = 1 if rsi < 35 else -1 if rsi > 65 else 0

    score = ichi_vote + macd_vote + rsi_vote
    signal = "buy" if score >= 2 else "sell" if score <= -2 else "hold"
    return {
        "price": price,
        "ichi_vote": ichi_vote,
        "ichi_text": ichi_text,
        "macd_vote": macd_vote,
        "rsi": rsi,
        "rsi_vote": rsi_vote,
        "score": score,
        "signal": signal,
    }


# ------------------------------------------------------------ صدا
def make_beep_wav(path: str, freqs: list) -> None:
    rate = 22050
    frames = bytearray()
    for freq in freqs:
        n = int(rate * 0.22)
        for i in range(n):
            env = min(1.0, i / (rate * 0.02)) * (1 - i / n)
            frames += struct.pack("<h", int(12000 * env * math.sin(2 * math.pi * freq * i / rate)))
        frames += b"\x00\x00" * int(rate * 0.03)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


# ------------------------------------------------------------ کمکی UI
def vote_color(v: int) -> str:
    return COLORS["buy"] if v > 0 else COLORS["sell"] if v < 0 else MUTE


def vote_sym(v: int) -> str:
    return "▲" if v > 0 else "▼" if v < 0 else "●"


def fmt_price(p: float) -> str:
    if p >= 1:
        return f"{p:,.2f}"
    if p >= 0.0001:
        return f"{p:,.4f}"
    return f"{p:,.8f}"


def box(left=0, top=0, right=0, bottom=0):
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)


def outline(width, color):
    side = ft.BorderSide(width, color)
    return ft.Border(left=side, top=side, right=side, bottom=side)


class State:
    def __init__(self) -> None:
        self.coins = load_coins()
        self.tf = "1h"
        self.alarm = False
        self.prev = {}


async def main(page: ft.Page):
    page.title = "دیدبان سیگنال رمزارز"
    page.padding = 14
    setattr(page, "rtl", True)
    page.fonts = {"Vazirmatn": FONT_URL}
    page.theme = ft.Theme(font_family="Vazirmatn")
    page.theme_mode = ft.ThemeMode.SYSTEM

    st = State()
    wake = asyncio.Event()

    # صدای موبایل (اختیاری؛ اگر بسته flet_audio نبود فقط اعلان داخل برنامه نشان داده می‌شود)
    players: list = []
    beep_files = {
        "buy": os.path.join(STORAGE_DIR, "buy.wav"),
        "sell": os.path.join(STORAGE_DIR, "sell.wav"),
    }
    if sys.platform != "win32":
        try:
            make_beep_wav(beep_files["buy"], [880, 1175])
            make_beep_wav(beep_files["sell"], [440, 330])
            fta = importlib.import_module("flet_audio")
            new_player = fta.Audio(src=beep_files["buy"], autoplay=False)
            page.overlay.append(new_player)
            players.append(new_player)
        except (ImportError, OSError, TypeError, ValueError):
            players.clear()

    async def play_beep(kind: str) -> None:
        try:
            if sys.platform == "win32":
                import winsound

                notes = [(880, 200), (1175, 200)] if kind == "buy" else [(440, 200), (330, 200)]
                for freq, dur in notes:
                    await asyncio.to_thread(winsound.Beep, freq, dur)
            else:
                for player in players:
                    player.src = beep_files[kind]
                    player.update()
                    res = player.play()
                    if inspect.isawaitable(res):
                        await res
        except (ImportError, OSError, RuntimeError, AttributeError, TypeError):
            pass

    async def notify(symbol: str, kind: str) -> None:
        await play_beep(kind)
        try:
            bar = ft.SnackBar(ft.Text(f"{symbol}: {SIGNAL_TEXT[kind]}"), duration=8000)
            opener = getattr(page, "show_dialog", None) or getattr(page, "open")
            opener(bar)
        except (AttributeError, TypeError):
            pass

    # کنترل‌ها
    status = ft.Text("", size=12, color=MUTE)
    listview = ft.ListView(expand=True, spacing=10)
    symbol_field = ft.TextField(
        hint_text="مثلاً ADA",
        width=120,
        dense=True,
        text_align=ft.TextAlign.LEFT,
        capitalization=ft.TextCapitalization.CHARACTERS,
    )

    tf_buttons = {}

    def style_tf() -> None:
        for key, btn in tf_buttons.items():
            active = key == st.tf
            btn.style = ft.ButtonStyle(
                color=COLORS["buy"] if active else None,
                side=ft.BorderSide(1, COLORS["buy"] if active else LINE),
            )
            btn.update()

    def make_tf_handler(chosen: str):
        def handler(_e=None):
            st.tf = chosen
            st.prev = {}
            style_tf()
            wake.set()

        return handler

    tf_row = ft.Row(wrap=True, spacing=6)
    for tf_value, tf_label in TIMEFRAMES:
        b = OutlinedButton(content=ft.Text(tf_label), on_click=make_tf_handler(tf_value))
        tf_buttons[tf_value] = b
        tf_row.controls.append(b)

    def add_coin(_e=None):
        raw = symbol_field.value or ""
        sym = "".join(ch for ch in raw.strip().upper() if ch.isascii() and ch.isalnum())
        if sym and sym not in st.coins:
            st.coins.append(sym)
            save_coins(st.coins)
            wake.set()
        symbol_field.value = ""
        symbol_field.update()

    def make_remove_handler(sym: str):
        def handler(_e=None):
            st.coins = [c for c in st.coins if c != sym]
            save_coins(st.coins)
            wake.set()

        return handler

    alarm_label = ft.Text("فعال‌سازی آلارم")
    alarm_btn = OutlinedButton(content=alarm_label)
    test_btn = TextButton(content=ft.Text("تست صدا"), visible=False)

    async def toggle_alarm(_e=None):
        st.alarm = not st.alarm
        alarm_label.value = "آلارم فعال است" if st.alarm else "فعال‌سازی آلارم"
        alarm_btn.style = ft.ButtonStyle(color=COLORS["buy"] if st.alarm else None)
        test_btn.visible = st.alarm
        page.update()
        if st.alarm:
            await play_beep("buy")

    async def test_sound(_e=None):
        await play_beep("buy")

    alarm_btn.on_click = toggle_alarm
    test_btn.on_click = test_sound
    symbol_field.on_submit = add_coin
    add_btn = Button(content=ft.Text("افزودن"), on_click=add_coin)

    def make_card(sym: str, a: dict = None, err: str = ""):
        remove = ft.IconButton(
            icon=ft.Icons.CLOSE, icon_size=18, on_click=make_remove_handler(sym), tooltip=f"حذف {sym}"
        )
        sym_text = ft.Text(f"{sym}/USDT", weight=ft.FontWeight.W_800, size=16)

        if a is None:
            bar_color = COLORS["hold"]
            body = ft.Column(
                [
                    ft.Row([sym_text, remove], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(err, color=COLORS["sell"], size=13),
                ],
                spacing=4,
            )
        else:
            bar_color = COLORS[a["signal"]]
            head = ft.Row(
                [
                    sym_text,
                    ft.Text(f"${fmt_price(a['price'])}", color=MUTE),
                    ft.Container(expand=True),
                    ft.Text(
                        SIGNAL_TEXT[a["signal"]],
                        weight=ft.FontWeight.W_800,
                        size=16,
                        color=bar_color,
                    ),
                    remove,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

            def ind(name: str, vote: int, text: str):
                return ft.Text(
                    spans=[
                        ft.TextSpan(f"{name} "),
                        ft.TextSpan(
                            f"{vote_sym(vote)} {text}",
                            ft.TextStyle(color=vote_color(vote), weight=ft.FontWeight.W_600),
                        ),
                    ],
                    size=13,
                    color=MUTE,
                )

            macd_t = (
                "بالای سیگنال"
                if a["macd_vote"] > 0
                else "زیر سیگنال"
                if a["macd_vote"] < 0
                else "خنثی"
            )
            body = ft.Column(
                [
                    head,
                    ft.Row(
                        [
                            ind("ایچیموکو", a["ichi_vote"], a["ichi_text"]),
                            ind("مکدی", a["macd_vote"], macd_t),
                            ind("RSI", a["rsi_vote"], f"{a['rsi']:.1f}"),
                        ],
                        wrap=True,
                        spacing=16,
                        run_spacing=4,
                    ),
                ],
                spacing=6,
            )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=6, bgcolor=bar_color, border_radius=3),
                    ft.Container(body, expand=True),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            padding=box(12, 10, 12, 10),
            border=outline(1, LINE),
            border_radius=10,
        )

    async def refresh() -> None:
        status.value = "در حال به‌روزرسانی…"
        status.update()
        tf = st.tf
        cards = []
        for sym in list(st.coins):
            try:
                data = await asyncio.to_thread(fetch_klines, sym, tf)
                a = analyze(data)
                key = f"{sym}_{tf}"
                old = st.prev.get(key)
                if st.alarm and old and old != a["signal"] and a["signal"] != "hold":
                    await notify(sym, a["signal"])
                st.prev[key] = a["signal"]
                cards.append(make_card(sym, a))
            except (RuntimeError, ValueError, ZeroDivisionError) as ex:
                cards.append(make_card(sym, None, str(ex)))
            await asyncio.sleep(0.15)
        listview.controls = cards
        status.value = "آخرین به‌روزرسانی: " + time.strftime("%H:%M:%S")
        page.update()

    page.add(
        ft.SafeArea(
            ft.Column(
                [
                    ft.Text("دیدبان سیگنال رمزارز", size=24, weight=ft.FontWeight.W_800),
                    tf_row,
                    ft.Row([symbol_field, add_btn, alarm_btn, test_btn], wrap=True, spacing=8),
                    status,
                    listview,
                    ft.Text(
                        "سیگنال از رأی سه اندیکاتور ساخته می‌شود: ایچیموکو (ابر شیفت‌یافته)، "
                        "مکدی و RSI14. دست‌کم دو رأی هم‌جهت لازم است و فقط کندل بسته‌شده "
                        "مبنا قرار می‌گیرد. این ابزار توصیه مالی نیست.",
                        size=12,
                        color=MUTE,
                    ),
                ],
                expand=True,
                spacing=10,
            ),
            expand=True,
        )
    )
    style_tf()

    while True:
        wake.clear()
        await refresh()
        try:
            await asyncio.wait_for(wake.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass


_run = getattr(ft, "run", None) or getattr(ft, "app")
_run(main)
