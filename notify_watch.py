"""Folyamatos (közel azonnali) figyelő – felhőben vagy lokálisan.

A `notify_cron.py` EGYszer-fut logikáját ismétli egy loopban: alapból ~90
mp-enként keres value betet és AZONNAL emailt küld az ÚJAKRÓL. Így nem kell a
~15-30 perces időzített futásra várni – amint feltűnik egy biztos value bet,
pár tíz másodpercen belül jön az email.

Hol fut:
- A GitHub Actions felhőjében (`.github/workflows/value-watch.yml`), így a
  laptop KIKAPCSOLVA is megy.
- Vagy lokálisan: `python notify_watch.py` (amíg a gép be van kapcsolva).

Dedup: a `notified.json` (közös a cron megoldással), hogy ne spammeljen.

Környezeti változók:
  SMTP_USER, SMTP_PASSWORD, TO_EMAIL  – mint a cronnál (GitHub secrets).
  POLL_SEC          – ennyi mp-enként keres (alap 90).
  MAX_RUNTIME_SEC   – ennyi mp után tisztán kilép (alap 3300 = 55 perc),
                      hogy a CI a következő ütemezett futással folytassa.
"""
import json
import os
import time
import traceback
from datetime import datetime

from valuebet.notify import EmailNotifier
from valuebet.telegram import TelegramNotifier
import notify_cron

STATE_FILE = notify_cron.STATE_FILE
KEEP_SEC = notify_cron.KEEP_SEC


def load_config():
    path = "config.json" if os.path.exists("config.json") else "config.example.json"
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return notify_cron.inject_env(cfg)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def send_alerts(new, email, tg, cfg):
    """Telegram és/vagy email az ÚJ tippekről.

    A csatornák FÜGGETLENEK: ha legalább az egyik kiment, a hívó 'elküldött'-nek
    jelölheti a tippeket (nem küldjük újra). Csak akkor dob hibát (újrapróba), ha
    EGYIK csatorna sem ért célba. Így egy email-hiba nem okoz Telegram-újraküldést."""
    new.sort(key=lambda x: -x[2]["value_pct"])
    items = [(v, b) for _, v, b in new]
    delivered = False
    if tg.configured():
        try:
            notify_cron.send_telegram(tg, cfg, items)
            delivered = True
        except Exception as e:
            print(f"[telegram] HIBA: {e}")
    if cfg.get("notify", {}).get("enabled") and email.configured():
        try:
            text, html = notify_cron.build_email(
                cfg, items, f"{len(new)} új biztos value tipp a vegas.hu-n:")
            email.send(f"🟢 {len(new)} új value tipp – legjobb +{new[0][2]['value_pct']}%",
                       text, html)
            delivered = True
        except Exception as e:
            print(f"[email] HIBA: {e}")
    if not delivered:
        raise RuntimeError("egyik értesítési csatorna sem ért célba")


def main():
    cfg = load_config()
    email = EmailNotifier(cfg)
    tg = TelegramNotifier(cfg)
    if not (email.configured() or tg.configured()):
        print("HIBA: sem email (SMTP_*), sem Telegram (TELEGRAM_*) nincs beállítva.")
        return

    poll = int(os.environ.get("POLL_SEC", "90"))
    max_runtime = int(os.environ.get("MAX_RUNTIME_SEC", "3300"))
    # STABILITÁS (opcionális): hány EGYMÁST KÖVETŐ keresésben kell látszania egy
    # tippnek a küldéshez. Alap=1 → azonnal megy (semmit nem szűrünk feleslegesen,
    # a duplázást a notified.json dedup kezeli). 2-re állítva (MIN_SCANS=2 env) a
    # villódzó/pillanatnyi odds kiesne, de egy gyors tippet is késleltetne.
    min_scans = int(os.environ.get("MIN_SCANS", "1"))
    seen_counts = {}
    started = time.time()
    state = load_state()
    print(f"Figyelő indul: poll={poll}s, min_scans={min_scans}, "
          f"futásidő<={max_runtime}s, ismert tippek={len(state)}")

    while True:
        cycle = time.time()
        try:
            found, now = notify_cron.scan(cfg)
            state = {k: t for k, t in state.items() if now - t < KEEP_SEC}

            # stabilitás: csak az tekinthető éretten, amit min_scans körön át láttunk
            found_keys = {k for k, _, _ in found}
            for k in list(seen_counts):
                if k not in found_keys:
                    del seen_counts[k]            # eltűnt -> a számláló nullázódik
            for k in found_keys:
                seen_counts[k] = seen_counts.get(k, 0) + 1
            ripe = {k for k, c in seen_counts.items() if c >= min_scans}

            new = [(k, v, b) for (k, v, b) in found if k in ripe and k not in state]
            sent_keys = {k for k, _, _ in new}

            sent_ok = True
            if new:
                try:
                    send_alerts(new, email, tg, cfg)
                    print(f"[{datetime.now():%H:%M:%S}] Elküldve {len(new)} ÚJ tipp "
                          f"(stabil: {len(ripe)}, összes találat: {len(found)}).")
                except Exception as e:
                    sent_ok = False
                    print(f"[{datetime.now():%H:%M:%S}] [értesítés] HIBA: {e} "
                          f"(újrapróbálom a következő körben)")
            else:
                print(f"[{datetime.now():%H:%M:%S}] Nincs új stabil tipp "
                      f"(stabil: {len(ripe)}, érlelődik: {len(found_keys) - len(ripe)}).")

            # Csak sikeres küldés után jegyezzük ismertnek a KIKÜLDÖTT tippeket,
            # és frissítjük a már ismertek TTL-jét (ne ébredjenek újra).
            if sent_ok:
                for k in found_keys:
                    if k in state or k in sent_keys:
                        state[k] = now
                save_state(state)
        except Exception:
            print(f"[{datetime.now():%H:%M:%S}] Ciklus hiba:\n"
                  + traceback.format_exc())

        if time.time() - started > max_runtime:
            print("Futásidő letelt, tiszta kilépés (a CI folytatja).")
            save_state(state)
            return
        time.sleep(max(5, poll - (time.time() - cycle)))


if __name__ == "__main__":
    main()
