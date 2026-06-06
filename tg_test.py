"""Próba Telegram-üzenet a felhőből (a GitHub secretekkel).

Ha van élő biztos value bet, a legjobb 1-3-at küldi el az ÉLES formátummal
(gombokkal). Ha nincs, egy jelölt PÉLDA tippet küld, hogy lásd, hogy néz ki.

Env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (GitHub secret).
"""
import os

from valuebet.telegram import TelegramNotifier, format_tip, BUTTONS
import notify_cron
from notify_test import sample_bet


def main():
    path = "config.json" if os.path.exists("config.json") else "config.example.json"
    cfg = notify_cron.json.load(open(path, encoding="utf-8"))
    notify_cron.inject_env(cfg)

    tg = TelegramNotifier(cfg)
    if not tg.configured():
        print("HIBA: nincs Telegram beállítva (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID).")
        return

    try:
        found, _ = notify_cron.scan(cfg)
    except Exception as e:
        print(f"Keresés hiba (példával folytatom): {e}")
        found = []

    if found:
        found.sort(key=lambda x: -x[2]["value_pct"])
        items = [(v, b) for _, v, b in found[:3]]
        intro = (f"✅ <b>PRÓBA</b> – a Telegram-figyelő működik. {len(found)} biztos "
                 f"tipp van; itt a legjobb {len(items)}. Próbáld ki a gombokat!")
    else:
        items = [sample_bet()]
        intro = ("✅ <b>PRÓBA</b> – a Telegram-figyelő működik. Most nincs élő biztos "
                 "tipp, ezért egy PÉLDA megy – próbáld ki rajta a gombokat! "
                 "(Erre ne fogadj.)")

    tg.send(intro)
    notify_cron.send_telegram(tg, cfg, items)
    print(f"Próba Telegram elküldve ({len(items)} tipp).")


if __name__ == "__main__":
    main()
