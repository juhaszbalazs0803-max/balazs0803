"""Próba-email küldése a felhőből (a GitHub secretekkel).

Ha épp van élő biztos value bet, a legjobb 1-3-at küldi el az ÉLES formátummal
(javasolt téttel és a tőke %-ával). Ha nincs, egy egyértelműen jelölt PÉLDA
tippet küld, hogy lásd, hogyan néz majd ki az email.

Env: SMTP_USER, SMTP_PASSWORD, TO_EMAIL (mint a többi felhős scriptnél).
"""
import os
from types import SimpleNamespace

from valuebet.notify import EmailNotifier
import notify_cron


def sample_bet():
    """Egy realisztikus PÉLDA value bet a formátum bemutatásához."""
    v = SimpleNamespace(sport_id=66, home="Példa Hazai FC", away="Példa Vendég SC")
    odds = 2.10
    fair_p = 0.50                       # ~5% value ezen az odds-on
    b = {
        "market_name": "Meccsgyőztes",
        "tip": "1 — Példa Hazai FC",
        "odds": odds,
        "fair_p": fair_p,
        "value_pct": round((fair_p * odds - 1) * 100, 2),
        "limit": 1500,
        "pinn_url": "https://www.pinnacle.com/",
    }
    return v, b


def main():
    path = "config.json" if os.path.exists("config.json") else "config.example.json"
    cfg = notify_cron.json.load(open(path, encoding="utf-8"))
    n = cfg.setdefault("notify", {})
    n["smtp_user"] = os.environ.get("SMTP_USER", n.get("smtp_user", ""))
    n["smtp_password"] = os.environ.get("SMTP_PASSWORD", n.get("smtp_password", ""))
    n["to_email"] = os.environ.get("TO_EMAIL", n.get("to_email") or n["smtp_user"])

    notifier = EmailNotifier(cfg)
    if not notifier.configured():
        print("HIBA: nincs SMTP beállítva (SMTP_USER / SMTP_PASSWORD / TO_EMAIL).")
        return

    try:
        found, _ = notify_cron.scan(cfg)
    except Exception as e:
        print(f"Keresés hiba (példával folytatom): {e}")
        found = []

    if found:
        found.sort(key=lambda x: -x[2]["value_pct"])
        top = found[:3]
        lines = ["✅ PRÓBA EMAIL – a figyelő működik.\n",
                 f"Most {len(found)} biztos value tipp van; itt a legjobb {len(top)}:\n"]
        for _, v, b in top:
            lines.append(notify_cron.format_bet(cfg, v, b))
        subject = f"✅ Próba email – működik ({len(found)} élő tipp)"
    else:
        v, b = sample_bet()
        lines = ["✅ PRÓBA EMAIL – a figyelő működik.\n",
                 "Most épp nincs élő biztos value tipp, ezért egy PÉLDA tippet "
                 "mutatok, hogy lásd, hogyan néz majd ki egy igazi értesítés:\n",
                 notify_cron.format_bet(cfg, v, b),
                 "(A fenti csak példa – ne fogadj rá!)\n"]
        subject = "✅ Próba email – működik (példa tipp)"

    lines.append("\nA javasolt tét a beállított tőkéből (bankroll) számolt negyed-Kelly,\n"
                 "100 Ft-ra kerekítve, és melléírva a tőke hány %-a.")
    notifier.send(subject, "\n".join(lines))
    print(f"Próba email elküldve: {subject}")


if __name__ == "__main__":
    main()
