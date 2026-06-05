"""Felhőben (pl. GitHub Actions) futtatható egyszeri kereső + email-küldő.

Lefuttat EGY keresést (vegas.hu + Pinnacle), kiszűri a biztos value beteket,
és emailt küld az ÚJAKRÓL (amikről még nem szólt). A már elküldötteket a
`notified.json` tárolja, hogy ne spammeljen.

Az SMTP belépési adatok KÖRNYEZETI VÁLTOZÓKBÓL jönnek (GitHub secrets), így
nem kerülnek a kódba:  SMTP_USER, SMTP_PASSWORD, TO_EMAIL
"""
import json
import os
from datetime import datetime, timezone

from valuebet.http import Http
from valuebet.vegas import VegasClient, SPORT_NAMES
from valuebet.pinnacle import PinnacleClient, SPORT_MAP
from valuebet.notify import EmailNotifier
from valuebet import matching, compute
from valuebet import value as V

STATE_FILE = "notified.json"
KEEP_SEC = 2 * 86400  # 2 napnál régebbi értesítéseket elfelejtünk


def _round_stake(x, step=100):
    return int(round(x / step) * step)


def stake_for(cfg, fair_p, odds):
    """Javasolt tét (Ft) és a tőke hány %-a – ugyanúgy mint a webes felület.

    tét = bankroll * Kelly-tört * kelly_fraction (negyed Kelly), 100-ra kerekítve,
    de legalább min_bet. A % a bankroll-hoz viszonyított arány.
    """
    bankroll = float(cfg.get("live", {}).get("bankroll", 0))
    mult = float(cfg.get("value", {}).get("kelly_fraction", 0.25))
    min_bet = float(cfg.get("live", {}).get("min_bet", 100))
    frac = V.kelly_fraction(fair_p, odds) * mult
    pct = frac * 100.0
    st = _round_stake(bankroll * frac)
    if 0 < st < min_bet:
        st = int(min_bet)
    return st, pct


def format_bet(cfg, v, b):
    """Egy value bet email-sora, a javasolt téttel és a tőke %-ával."""
    st, pct = stake_for(cfg, b["fair_p"], b["odds"])
    stake_str = f"{st:,}".replace(",", " ")  # ezres tagolás szóközzel
    return (
        f"• {SPORT_NAMES.get(v.sport_id, '')} | {v.home} - {v.away}\n"
        f"  {b['market_name']} – {b['tip']}\n"
        f"  Vegas odds {b['odds']:.2f} | value +{b['value_pct']}%"
        f" | Pinnacle limit ${b.get('limit', 0)}\n"
        f"  💰 Javasolt tét: {stake_str} Ft  (a tőke {pct:.1f}%-a)\n"
        f"  Ellenőrzés: {b.get('pinn_url', '')}\n")


def scan(cfg):
    http = Http(verify_ssl=cfg.get("http", {}).get("verify_ssl", True), delay_sec=0)
    vegas = VegasClient(http, cfg["vegas"])
    pinn = PinnacleClient(http)

    live = cfg.get("live", {})
    solid = live.get("solid", {})
    mcfg = cfg.get("matching", {})
    vcfg = cfg.get("value", {})
    devig = cfg.get("reference", {}).get("devig_method", "proportional")
    min_value = cfg.get("notify", {}).get("min_value_pct", 3.0)
    now = datetime.now(timezone.utc).timestamp()

    found = []
    for sid in live.get("sports", [66, 68, 67, 70]):
        ps = SPORT_MAP.get(sid)
        if not ps:
            continue
        try:
            ve, re_ = vegas.fetch_sport(sid), pinn.fetch_sport(ps)
        except Exception as e:
            print(f"  [{sid}] hiba: {e}")
            continue
        pairs = matching.match_events(ve, re_, mcfg.get("max_start_diff_minutes", 90),
                                      mcfg.get("min_token_score", 0.6))
        for v, r, sw, score in pairs:
            if score < solid.get("min_score", 0.8):
                continue
            for b in compute.compute_bets(v, r, sw, devig):
                val = b["value_pct"]
                if val < min_value or val > solid.get("max_value_pct", 20.0):
                    continue
                if b["odds"] < vcfg.get("min_odds", 1.2) or b["odds"] > solid.get("max_odds", 5.0):
                    continue
                if b.get("limit", 0) < solid.get("min_limit", 0):
                    continue
                mh = solid.get("max_hours_to_start", 0)
                if mh > 0:
                    if not v.start:
                        continue
                    hrs = (v.start.timestamp() - now) / 3600.0
                    if hrs < 0 or hrs > mh:
                        continue
                found.append((f"{sid}:{v.id}:{b['subkey']}", v, b))
    return found, now


def main():
    # Felhőben (publikus repo) csak config.example.json van; lokálisan config.json.
    path = "config.json" if os.path.exists("config.json") else "config.example.json"
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    n = cfg.setdefault("notify", {})
    n["smtp_user"] = os.environ.get("SMTP_USER", n.get("smtp_user", ""))
    n["smtp_password"] = os.environ.get("SMTP_PASSWORD", n.get("smtp_password", ""))
    n["to_email"] = os.environ.get("TO_EMAIL", n.get("to_email") or n["smtp_user"])

    notifier = EmailNotifier(cfg)
    if not notifier.configured():
        print("HIBA: nincs SMTP beállítva (SMTP_USER / SMTP_PASSWORD / TO_EMAIL).")
        return

    found, now = scan(cfg)

    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
    state = {k: t for k, t in state.items() if now - t < KEEP_SEC}

    new = [(k, v, b) for (k, v, b) in found if k not in state]
    for k, _, _ in found:
        state[k] = now
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

    if not new:
        print(f"Nincs új tipp ({len(found)} biztos, mind ismert).")
        return

    new.sort(key=lambda x: -x[2]["value_pct"])
    lines = [f"{len(new)} új biztos value tipp a vegas.hu-n:\n"]
    for _, v, b in new:
        lines.append(format_bet(cfg, v, b))
    notifier.send(f"🟢 {len(new)} új value tipp – legjobb +{new[0][2]['value_pct']}%",
                  "\n".join(lines))
    print(f"Elküldve: {len(new)} új tipp.")


if __name__ == "__main__":
    main()
