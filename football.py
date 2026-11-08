"""
Football (Premier League) draw-streak tracker: Aston Villa, Everton.

Principle (same as NHL): count consecutive matches WITHOUT a draw.
When the streak reaches FOOTBALL_MIN_STREAK, a Fibonacci-step bet on Draw (X)
is suggested for the next match, together with the bookmaker draw odds.

Data:
  - Results / fixtures: football-data.org (free tier, Premier League included)
  - Odds:               The Odds API (sport key: soccer_epl, market h2h -> Home/Draw/Away)

Run alone:      python football.py
Or from bot.py: from football import run_football ; run_football()
"""
import os
from datetime import datetime, timedelta, timezone

import requests

# --- Secrets come from environment variables (do NOT hardcode them) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API_KEY_ODDS = os.environ.get("API_KEY_ODDS", "")
FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")

# --- Settings ---
FOOTBALL_MIN_STREAK = 5        # from how many no-draw matches in a row we alert
BASE_UNIT = 100                # 100 AMD
COMPETITION = "PL"             # Premier League only (free tier)
YEREVAN_TZ = timezone(timedelta(hours=4))

# football-data.org team id -> name used by The Odds API
TEAMS = {
    58: "Aston Villa",
    62: "Everton",
}

FIBONACCI = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]


def get_fibonacci_bet(streak, min_streak, base_amount=BASE_UNIT):
    idx = max(0, streak - min_streak)
    idx = min(idx, len(FIBONACCI) - 1)
    units = FIBONACCI[idx]
    return idx + 1, units, f"{units * base_amount:,}"


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token/chat id not set, message not sent:\n" + msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"Telegram error: {e}")


def fetch_team_matches(team_id):
    """All Premier League matches of the current season for one team."""
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches"
    headers = {"X-Auth-Token": FOOTBALL_DATA_TOKEN}
    params = {"competitions": COMPETITION}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"football-data.org {r.status_code}: {r.text[:200]}")
    return r.json().get("matches", [])


def fetch_epl_odds():
    if not API_KEY_ODDS:
        return []
    url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
    params = {"apiKey": API_KEY_ODDS, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"Odds API error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"Odds API error: {e}")
    return []


def short(team):
    return team.get("shortName") or team.get("name") or "?"


def to_yerevan(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(YEREVAN_TZ).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return utc_str or "Անհայտ"


def find_odds(all_odds, team_name, opp_name):
    """Returns (bookmaker, home_team, home_price, draw_price, away_price, away_team) or None."""
    for game in all_odds:
        home, away = game.get("home_team", ""), game.get("away_team", "")
        names = {home, away}
        if team_name not in names:
            continue
        # opponent name may differ slightly between APIs, so match loosely
        other = away if home == team_name else home
        if opp_name and opp_name.split()[0].lower() not in other.lower():
            continue
        for bm in game.get("bookmakers", []):
            for m in bm.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                prices = {o.get("name"): o.get("price") for o in m.get("outcomes", [])}
                if "Draw" in prices:
                    return (bm.get("title", ""), home, prices.get(home), prices["Draw"], prices.get(away), away)
    return None


def analyse_team(team_id, odds_name, all_odds):
    matches = fetch_team_matches(team_id)

    finished = [m for m in matches if m.get("status") == "FINISHED"]
    finished.sort(key=lambda m: m.get("utcDate", ""), reverse=True)

    upcoming = [m for m in matches if m.get("status") in ("SCHEDULED", "TIMED")]
    upcoming.sort(key=lambda m: m.get("utcDate", ""))

    # consecutive matches without a draw (most recent first)
    streak = 0
    for m in finished:
        if m.get("score", {}).get("winner") == "DRAW":
            break
        streak += 1

    last_draw_ago = None
    for i, m in enumerate(finished):
        if m.get("score", {}).get("winner") == "DRAW":
            last_draw_ago = i
            break

    info = {"name": odds_name, "streak": streak, "played": len(finished),
            "last": "—", "next": "Անհայտ", "time": "Անհայտ", "odds": ""}

    if finished:
        m = finished[0]
        ft = m.get("score", {}).get("fullTime", {})
        info["last"] = f"{short(m['homeTeam'])} {ft.get('home')} - {ft.get('away')} {short(m['awayTeam'])}"

    if upcoming:
        n = upcoming[0]
        is_home = n["homeTeam"].get("id") == team_id
        opp = n["awayTeam"] if is_home else n["homeTeam"]
        opp_name = short(opp)
        info["next"] = f"vs {opp_name}" if is_home else f"@ {opp_name}"
        info["time"] = to_yerevan(n.get("utcDate", ""))

        o = find_odds(all_odds, odds_name, opp_name)
        if o:
            bm, home, hp, dp, ap, away = o
            info["odds"] = (f"   💰 <b>Գործակիցներ ({bm}):</b>\n"
                            f"   • {home}: <b>{hp}</b>\n"
                            f"   • <b>Ոչ-Ոքի (X): {dp}</b>\n"
                            f"   • {away}: <b>{ap}</b>\n")
    if last_draw_ago is None and finished:
        info["no_draw_season"] = True
    return info


def run_football(send=True):
    print("Starting Football (EPL) draw-streak tracker...")
    if not FOOTBALL_DATA_TOKEN:
        print("FOOTBALL_DATA_TOKEN is not set. Get a free token at https://www.football-data.org/client/register")
        return ""

    all_odds = fetch_epl_odds()
    lines = ["⚽ <b>EPL — ՇԱՐՔ ԱՌԱՆՑ ՈՉ-ՈՔԻԻ</b>\n"]

    for team_id, odds_name in TEAMS.items():
        try:
            t = analyse_team(team_id, odds_name, all_odds)
        except Exception as e:
            print(f"Football error for {odds_name}: {e}")
            lines.append(f"• <b>{odds_name}</b> — տվյալներ ստանալ չհաջողվեց\n")
            continue

        hot = t["streak"] >= FOOTBALL_MIN_STREAK
        mark = "🔥" if hot else "▫️"
        lines.append(f"{mark} <b>{t['name']}</b> — <code>{t['streak']} խաղ</code> անընդմեջ առանց ոչ-ոքիի")
        if t.get("no_draw_season"):
            lines.append(f"   (մրցաշրջանում դեռ ոչ-ոքի չկա, {t['played']} խաղ)")
        if hot:
            step, units, total = get_fibonacci_bet(t["streak"], FOOTBALL_MIN_STREAK)
            lines.append(f"   📊 <b>Ֆիբոնաչի Քայլ {step}:</b> <code>{units} unit</code> (<b>{total} ֏</b>) — X")
        lines.append(f"   ▫️ Վերջինը՝ <i>{t['last']}</i>")
        lines.append(f"   ▫️ Հաջորդը՝ <b>{t['next']}</b>")
        lines.append(f"   📅 Ժամը (Երևան)՝ <code>{t['time']}</code>")
        if t["odds"]:
            lines.append(t["odds"].rstrip("\n"))
        lines.append("")

    msg = "\n".join(lines)
    print(msg)
    if send:
        send_telegram(msg)
    return msg


if __name__ == "__main__":
    run_football()
