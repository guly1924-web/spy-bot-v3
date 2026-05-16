import os
import time
import json
import requests
from datetime import datetime
import pytz

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY")
POLYGON_KEY      = os.environ.get("POLYGON_API_KEY")
CAPITAL          = float(os.environ.get("CAPITAL", 50000))
RISK_PCT         = float(os.environ.get("RISK_PCT", 1.0))
INTERVAL_MIN     = int(os.environ.get("INTERVAL_MIN", 15))

ET = pytz.timezone("America/New_York")

def get_session():
    now = datetime.now(ET)
    h, m = now.hour, now.minute
    mins = h * 60 + m
    wd = now.weekday()
    if wd == 5:
        if mins >= 1080:
            return {"name":"Futuros /ES Sabado noche","active":True,"type":"futures","bonus":0,"min_score":80}
        return {"name":"Mercado cerrado Sabado","active":False,"type":"closed","bonus":-50,"min_score":999}
    if wd == 6:
        if mins >= 1080:
            return {"name":"Futuros /ES Domingo noche","active":True,"type":"futures","bonus":5,"min_score":78}
        return {"name":"Mercado cerrado Domingo","active":False,"type":"closed","bonus":-50,"min_score":999}
    if 0 <= mins < 240:
        return {"name":"Futuros Overnight","active":True,"type":"futures","bonus":-5,"min_score":82}
    if 240 <= mins < 540:
        return {"name":"Pre-Market","active":True,"type":"premarket","bonus":5,"min_score":78}
    if 540 <= mins < 570:
        return {"name":"Pre-Apertura","active":True,"type":"premarket","bonus":10,"min_score":75}
    if 570 <= mins < 660:
        return {"name":"Apertura","active":True,"type":"market","bonus":20,"min_score":70}
    if 660 <= mins < 690:
        return {"name":"Transicion","active":True,"type":"market","bonus":0,"min_score":80}
    if 690 <= mins < 840:
        return {"name":"Almuerzo BLOQUEADO","active":False,"type":"blocked","bonus":-20,"min_score":999}
    if 840 <= mins < 870:
        return {"name":"Pre-Cierre","active":True,"type":"market","bonus":5,"min_score":78}
    if 870 <= mins < 945:
        return {"name":"Cierre","active":True,"type":"market","bonus":15,"min_score":72}
    if 945 <= mins < 1080:
        return {"name":"After-Hours","active":True,"type":"afterhours","bonus":-5,"min_score":82}
    if mins >= 1080:
        return {"name":"Futuros Noche","active":True,"type":"futures","bonus":0,"min_score":80}
    return {"name":"Fuera de mercado","active":False,"type":"closed","bonus":-50,"min_score":999}

def get_spy_price():
    try:
        url = f"https://api.polygon.io/v2/last/trade/SPY?apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=10).json()
        return float(r["results"]["p"])
    except:
        return None

def get_vix():
    try:
        url = f"https://api.polygon.io/v2/last/trade/VIXY?apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=10).json()
        return float(r["results"]["p"])
    except:
        return 18.0

def get_es_data():
    try:
        url = f"https://api.polygon.io/v2/last/trade/ESM26?apiKey={POLYGON_KEY}"
        r = requests.get(url, timeout=10).json()
        price = float(r["results"]["p"])
        url2 = f"https://api.polygon.io/v2/aggs/ticker/ESM26/prev?apiKey={POLYGON_KEY}"
        r2 = requests.get(url2, timeout=10).json()
        prev = float(r2["results"][0]["c"])
        chg = round((price - prev) / prev * 100, 2)
        return {"price": price, "change_pct": chg, "bullish": chg > 0.15}
    except:
        return {"price": 0, "change_pct": 0, "bullish": False}

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
            return {
                "strike": best.get("details", {}).get("strike_price", strike),
                "exp": best.get("details", {}).get("expiration_date", exp),
                "bid": best.get("last_quote", {}).get("bid", 0),
                "ask": best.get("last_quote", {}).get("ask", 0),
                "delta": abs(best.get("greeks", {}).get("delta", 0.50)),
                "volume": best.get("day", {}).get("volume", 0),
                "oi": best.get("open_interest", 0),
            }
    except:
        pass
    strike = round(spy_price) + (1 if direction == "LONG" else -1)
    return {"strike": strike, "exp": "0DTE", "bid": 1.10, "ask": 1.25, "delta": 0.50, "volume": 0, "oi": 0}

def claude_analysis(spy_price, es_data, vix, session):
    sess_type = session.get("type", "market")
    if sess_type in ["futures", "afterhours", "premarket"]:
        instrument = f"/ES Futuros ${es_data['price']} ({es_data['change_pct']:+.2f}%)"
        context = "Analiza principalmente los futuros /ES para detectar movimientos institucionales."
    else:
        instrument = f"SPY ${spy_price}"
        context = "Analiza SPY con todas las capas del metodo Infusion."
    prompt = f"""Eres experto en tape reading metodo Victor Gonzalez Infusion Investments. Vigilas 24/7.
DATOS: Instrumento={instrument} SPY=${spy_price} ES=${es_data['price']} ({es_data['change_pct']:+.2f}%) VIX={vix} Sesion={session['name']}
{context}
Aplica tape reading: UA sweeps/blocks, delta bid/ask, ES direccion, GEX MaxPain, estructura HH/HL o LH/LL, VIX, ventana probabilidad, doble confirmacion, volumen.
Solo LONG o SHORT con evidencia real de ballenas. Sin unusual activity clara devuelve WAIT o NONE.
Responde SOLO JSON sin texto extra: {{"direction":"LONG o SHORT o WAIT o NONE","score":0-100,"ua_detected":true,"es_bullish":true,"layers_passed":0-9,"vix_ok":true,"reason":"max 20 palabras"}}"""
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY,"anthropic-version": "2023-06-01","content-type": "application/json"},
            json={"model": "claude-sonnet-4-20250514","max_tokens": 300,"messages": [{"role": "user", "content": prompt}]},
            timeout=30
        )
        text = r.json()["content"][0]["text"]
        text = text.replace("```json","").replace("```","").strip()
        return json.loads(text)
    except Exception as e:
        return {"direction":"NONE","score":0,"layers_passed":0,"ua_detected":False,"reason":f"Error: {e}"}

def calc_risk(spy_price, direction, option):
    risk_dollar = round(CAPITAL * RISK_PCT / 100)
    ask = option.get("ask", 1.25)
    if ask <= 0: ask = 1.25
    contracts = max(1, int(risk_dollar / (ask * 100)))
    prima = round(contracts * ask * 100)
    if direction == "LONG":
        entry=spy_price; tp1=round(spy_price*1.008,2); tp2=round(spy_price*1.016,2); sl=round(spy_price*0.994,2)
    else:
        entry=spy_price; tp1=round(spy_price*0.992,2); tp2=round(spy_price*0.984,2); sl=round(spy_price*1.006,2)
    return {"entry":entry,"tp1":tp1,"tp2":tp2,"sl":sl,"contracts":contracts,"prima":prima,"risk":risk_dollar,
            "gain1":round(contracts*ask*100*1.6),"gain2":round(contracts*ask*100*3.2)}

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID,"text": msg,"parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

def build_message(direction, analysis, risk, option, spy_price, es_data, vix, session, score):
    now = datetime.now(ET).strftime("%I:%M %p ET")
    strike = option.get("strike", round(spy_price))
    opt_type = "C" if direction == "LONG" else "P"
    emoji = "🐋 LONG — EJECUTA" if direction == "LONG" else "🦈 SHORT — EJECUTA"
    return f"""🤖 <b>SPY Bot v3 · {now}</b>
{emoji}

Entrada   <code>${risk['entry']}</code>
Profit 1  <code>${risk['tp1']}</code>
Profit 2  <code>${risk['tp2']}</code>
Stop      <code>${risk['sl']}</code>

Compra <b>{risk['contracts']} {opt_type} del ${strike}</b>
Prima total <code>${risk['prima']}</code> = 1% de $50,000
Ganancia P1 <code>+${risk['gain1']}</code> · P2 <code>+${risk['gain2']}</code>
Confianza <b>{score}/100</b> · {analysis['layers_passed']}/9 capas

/ES <code>${es_data['price']} ({es_data['change_pct']:+.2f}%)</code>
VIX <code>{vix}</code> · {session['name']}"""

last_direction = "NONE"
confirm_count = 0
last_signal_time = 0

def run_cycle():
    global last_direction, confirm_count, last_signal_time
    session = get_session()
    now_str = datetime.now(ET).strftime("%H:%M ET")
    print(f"[{now_str}] Sesion: {session['name']} | Activa: {session['active']}")
    if not session["active"]:
        print(f"[{now_str}] Sesion bloqueada")
        return
    spy = get_spy_price()
    if not spy:
        return
    vix = get_vix()
    es = get_es_data()
    if vix > 35:
        send_telegram("🚨 <b>VIX > 35 MERCADO EN PANICO</b>\nBot congelado. Protege el fondeo.")
        return
    analysis = claude_analysis(spy, es, vix, session)
    direction = analysis.get("direction", "NONE")
    score = analysis.get("score", 0)
    min_score = session["min_score"]
    if vix > 25: min_score = max(min_score, 85)
    elif vix > 15: min_score = max(min_score, 78)
    print(f"[{now_str}] SPY ${spy} | ES ${es['price']} | Score {score} | Dir {direction} | VIX {vix}")
    if direction == last_direction and direction in ["LONG", "SHORT"]:
        confirm_count += 1
    else:
        confirm_count = 1
    last_direction = direction
    now_ts = time.time()
    if score >= min_score and direction in ["LONG","SHORT"] and confirm_count >= 2:
        if now_ts - last_signal_time > 1800:
            option = get_best_option(spy, direction)
            risk = calc_risk(spy, direction, option)
            msg = build_message(direction, analysis, risk, option, spy, es, vix, session, score)
            send_telegram(msg)
            last_signal_time = now_ts
            confirm_count = 0
            print(f"[{now_str}] SENAL ENVIADA: {direction} score {score}")
        else:
            print(f"[{now_str}] Anti-spam activo")
    elif direction in ["LONG","SHORT"] and confirm_count == 1:
        print(f"[{now_str}] Ciclo 1 confirmado ({score}) esperando ciclo 2")
    else:
        print(f"[{now_str}] Sin senal score {score} bajo umbral {min_score}")

if __name__ == "__main__":
    print("SPY Bot v3 Infusion Method 24/7 Iniciando...")
    send_telegram("🤖 <b>SPY Bot v3 — 24/7 Activado</b>\nMetodo Infusion · 9 capas · Fondeo $50K\n🐋 Vigilando el tape las 24 horas...")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(INTERVAL_MIN * 60)