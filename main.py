import os
import time
import json
import requests
from datetime import datetime, timezone
import pytz

# ─── CONFIG ───────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY")
POLYGON_KEY      = os.environ.get("POLYGON_API_KEY")
CAPITAL          = float(os.environ.get("CAPITAL", 50000))
RISK_PCT         = float(os.environ.get("RISK_PCT", 1.0))
INTERVAL_MIN     = int(os.environ.get("INTERVAL_MIN", 15))

ET = pytz.timezone("America/New_York")

# ─── SESIÓN ───────────────────────────────────────────────
def get_session():
    now = datetime.now(ET)
    h, m = now.hour, now.minute
    mins = h * 60 + m
    if 570 <= mins < 660:  return {"name": "Apertura ⚡⚡⚡", "active": True,  "bonus": 15, "min_score": 70}
    if 660 <= mins < 690:  return {"name": "Transición",     "active": False, "bonus": 0,  "min_score": 80}
    if 690 <= mins < 840:  return {"name": "Almuerzo 🔴",    "active": False, "bonus": -20,"min_score": 999}
    if 840 <= mins < 870:  return {"name": "Pre-cierre",     "active": False, "bonus": 0,  "min_score": 80}
    if 870 <= mins < 945:  return {"name": "Cierre ⚡⚡",     "active": True,  "bonus": 10, "min_score": 75}
    return {"name": "Fuera de mercado 🔴", "active": False, "bonus": -30, "min_score": 999}

# ─── POLYGON: PRECIO SPY ──────────────────────────────────
def get_spy_price():
    try:
        url = f"https://api.polygon.io/v2/last/trade/SPY?apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=10).json()
        return float(r["results"]["p"])
    except:
        return None

# ─── POLYGON: VIX ─────────────────────────────────────────
def get_vix():
    try:
        url = f"https://api.polygon.io/v2/last/trade/VIXY?apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=10).json()
        return float(r["results"]["p"])
    except:
        return 18.0

# ─── POLYGON: /ES FUTUROS ─────────────────────────────────
def get_es_data():
    try:
        url = f"https://api.polygon.io/v2/last/trade/ESM26?apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=10).json()
        price = float(r["results"]["p"])
        url2 = f"https://api.polygon.io/v2/aggs/ticker/ESM26/prev?apiKey={POLYGON_KEY}"
        r2 = requests.get(url2, timeout=10).json()
        prev = float(r2["results"][0]["c"])
        chg = round((price - prev) / prev * 100, 2)
        return {"price": price, "change_pct": chg}
    except:
        return {"price": 0, "change_pct": 0}

# ─── POLYGON: OPTION CHAIN SPY ────────────────────────────
def get_best_option(spy_price, direction):
    try:
        exp = datetime.now(ET).strftime("%Y-%m-%d")
        opt_type = "call" if direction == "LONG" else "put"
        strike = round(spy_price) + (1 if direction == "LONG" else -1)
        url = (f"https://api.polygon.io/v3/snapshot/options/SPY?"
               f"strike_price={strike}&contract_type={opt_type}"
               f"&expiration_date={exp}&limit=5&apiKey={POLYGON_KEY}")
        r = requests.get(url, timeout=10).json()
        results = r.get("results", [])
        if results:
            best = results[0]
            details = best.get("details", {})
            greeks = best.get("greeks", {})
            day = best.get("day", {})
            return {
                "strike": details.get("strike_price", strike),
                "exp": details.get("expiration_date", exp),
                "bid": best.get("last_quote", {}).get("bid", 0),
                "ask": best.get("last_quote", {}).get("ask", 0),
                "delta": abs(greeks.get("delta", 0.50)),
                "volume": day.get("volume", 0),
                "oi": best.get("open_interest", 0),
            }
    except:
        pass
    strike = round(spy_price) + (1 if direction == "LONG" else -1)
    return {"strike": strike, "exp": "0DTE", "bid": 1.10, "ask": 1.25, "delta": 0.50, "volume": 0, "oi": 0}

# ─── CLAUDE ANÁLISIS ──────────────────────────────────────
def claude_analysis(spy_price, es_data, vix, session):
    prompt = f"""Eres un analista experto en tape reading usando el método de Víctor González de Infusion Investments.

DATOS EN TIEMPO REAL:
- SPY precio: ${spy_price}
- /ES Futuros: ${es_data['price']} ({es_data['change_pct']:+.2f}% vs ayer)
- VIX: {vix}
- Sesión ET: {session['name']}

Analiza usando las 9 capas del método Infusion:
1. /ES Futuros dirección (20pts)
2. Unusual Activity calls vs puts (20pts)
3. GEX + Max Pain SPX (15pts)
4. Estructura técnica 1m/5m/15m (15pts)
5. Time & Sales /ES tamaño ordenes (10pts)
6. VIX filtro riesgo (10pts)
7. Sesión ET ventana (5pts)
8. Doble confirmación (5pts)
9. Strike exacto option chain (implícito)

Responde SOLO en JSON sin texto extra:
{{
  "direction": "LONG" o "SHORT" o "WAIT" o "NONE",
  "score": número 0-100,
  "ua_calls": número 0-100,
  "ua_puts": número 0-100,
  "gex": "positivo" o "negativo",
  "max_pain_above": true o false,
  "trend_aligned": true o false,
  "es_bullish": true o false,
  "layers_passed": número 0-9,
  "reason": "máximo 15 palabras explicando la señal"
}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        text = r.json()["content"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return {"direction": "NONE", "score": 0, "layers_passed": 0,
                "ua_calls": 50, "ua_puts": 50, "reason": f"Error API: {e}"}

# ─── CALCULAR RIESGO ──────────────────────────────────────
def calc_risk(spy_price, direction, option):
    risk_dollar = round(CAPITAL * RISK_PCT / 100)
    ask = option.get("ask", 1.25)
    if ask <= 0: ask = 1.25
    contracts = max(1, int(risk_dollar / (ask * 100)))
    prima_total = round(contracts * ask * 100)

    if direction == "LONG":
        entry  = spy_price
        tp1    = round(spy_price * 1.008, 2)
        tp2    = round(spy_price * 1.016, 2)
        sl     = round(spy_price * 0.994, 2)
    else:
        entry  = spy_price
        tp1    = round(spy_price * 0.992, 2)
        tp2    = round(spy_price * 0.984, 2)
        sl     = round(spy_price * 1.006, 2)

    gain1 = round(contracts * ask * 100 * 1.6)
    gain2 = round(contracts * ask * 100 * 3.2)
    rr    = "1.6:1"

    return {
        "entry": entry, "tp1": tp1, "tp2": tp2, "sl": sl,
        "contracts": contracts, "prima": prima_total,
        "risk": risk_dollar, "gain1": gain1, "gain2": gain2, "rr": rr
    }

# ─── ENVIAR TELEGRAM ──────────────────────────────────────
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }, timeout=10)

def build_message(direction, analysis, risk, option, spy_price, es_data, vix, session, score):
    now = datetime.now(ET).strftime("%I:%M %p ET")
    strike = option.get("strike", round(spy_price))
    opt_type = "C" if direction == "LONG" else "P"
    dte = option.get("exp", "0DTE")
    vol = option.get("volume", 0)
    oi  = option.get("oi", 1)
    ratio = round(vol / oi, 1) if oi > 0 else 0

    if direction == "LONG":
        emoji = "🐋 LONG — EJECUTA"
    elif direction == "SHORT":
        emoji = "🦈 SHORT — EJECUTA"
    elif direction == "WAIT":
        emoji = "👀 ESPERAR — Sin entrada"
    else:
        emoji = "⛔ SIN SEÑAL — Protege el fondeo"

    if direction in ["LONG", "SHORT"]:
        msg = f"""🤖 <b>SPY Bot v3 · {now}</b>
{emoji}

Entrada   <code>${risk['entry']}</code>
Profit 1  <code>${risk['tp1']}</code>
Profit 2  <code>${risk['tp2']}</code>
Stop      <code>${risk['sl']}</code>

Compra <b>{risk['contracts']} {opt_type} del ${strike}</b> · {dte}
Prima total <code>${risk['prima']}</code> = 1% de ${int(CAPITAL):,}
Ganancia P1 <code>+${risk['gain1']}</code> · P2 <code>+${risk['gain2']}</code>
Confianza <b>{score}/100</b> · {analysis['layers_passed']}/9 capas ✅

/ES <code>${es_data['price']} ({es_data['change_pct']:+.2f}%)</code>
VIX <code>{vix}</code> · Sesión {session['name']}"""
    else:
        msg = f"""🤖 <b>SPY Bot v3 · {now}</b>
{emoji}

Score <b>{score}/100</b> · {analysis['layers_passed']}/9 capas
SPY <code>${spy_price}</code> · /ES <code>${es_data['price']}</code>
VIX <code>{vix}</code> · {session['name']}

{analysis.get('reason', 'Esperando confluencia')}"""

    return msg

# ─── LOOP PRINCIPAL ───────────────────────────────────────
last_score = 0
last_direction = "NONE"
confirm_count = 0

def run_cycle():
    global last_score, last_direction, confirm_count

    session = get_session()
    now_et = datetime.now(ET).strftime("%H:%M ET")
    print(f"[{now_et}] Sesión: {session['name']} | Activa: {session['active']}")

    if not session["active"]:
        print(f"[{now_et}] Sesión bloqueada — sin análisis")
        return

    spy = get_spy_price()
    if not spy:
        print("Error jalando precio SPY")
        return

    vix = get_vix()
    es  = get_es_data()

    # Filtro VIX extremo
    if vix > 35:
        send_telegram("🚨 <b>VIX &gt; 35 — MERCADO EN PÁNICO</b>\nBot congelado. Protege el fondeo. Sin operaciones.")
        return

    analysis = claude_analysis(spy, es, vix, session)
    direction = analysis.get("direction", "NONE")
    score = analysis.get("score", 0)

    # Ajuste por VIX
    min_score = session["min_score"]
    if vix > 25: min_score = max(min_score, 85)
    elif vix > 15: min_score = max(min_score, 78)

    print(f"[{now_et}] SPY ${spy} | Score {score} | Dir {direction} | VIX {vix}")

    # Doble confirmación
    if direction == last_direction and direction in ["LONG", "SHORT"]:
        confirm_count += 1
    else:
        confirm_count = 1

    last_direction = direction
    last_score = score

    if score >= min_score and direction in ["LONG", "SHORT"] and confirm_count >= 2:
        option = get_best_option(spy, direction)
        risk   = calc_risk(spy, direction, option)
        msg    = build_message(direction, analysis, risk, option, spy, es, vix, session, score)
        send_telegram(msg)
        print(f"[{now_et}] ✅ SEÑAL ENVIADA: {direction} score {score}")
        confirm_count = 0
    elif direction in ["LONG", "SHORT"] and confirm_count == 1:
        print(f"[{now_et}] Ciclo 1 confirmado ({score}) — esperando ciclo 2")
    else:
        print(f"[{now_et}] Sin señal — score {score} bajo umbral {min_score}")

if __name__ == "__main__":
    print("🚀 SPY Bot v3 — Infusion Method — Iniciando...")
    send_telegram("🤖 <b>SPY Bot v3 iniciado</b>\nMétodo Infusion · 9 capas · Fondeo $50K\nEsperando apertura del mercado...")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"Error en ciclo: {e}")
        time.sleep(INTERVAL_MIN * 60)
