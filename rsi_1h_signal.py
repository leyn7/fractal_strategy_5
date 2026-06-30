"""
Paso 1 de la estrategia: RSI 1H del BNBUSDT (Binance Futures).
Calcula RSI(14) con suavizado de Wilder y reporta cual fue la ULTIMA ZONA
donde estuvo el RSI:
  - SOBREVENTA  = RSI <= 30
  - SOBRECOMPRA = RSI >= 70
Horario: Bogota (UTC-5), formato 24H.
"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta

SYMBOL = "BNBUSDT"
INTERVAL = "1h"
RSI_PERIOD = 14
OVERSOLD = 30
OVERBOUGHT = 70
RECOVERY = 40   # nivel al que el RSI debe volver para dar por terminado el tramo
LIMIT = 500  # velas a descargar (suficiente historial)

BOGOTA = timezone(timedelta(hours=-5))


def fetch_klines():
    url = (
        f"https://fapi.binance.com/fapi/v1/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
    )
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read())


def rsi_wilder(closes, period=14):
    """RSI con suavizado de Wilder (igual que TradingView/Binance)."""
    rsis = [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    if len(gains) < period:
        return rsis
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def to_rsi(ag, al):
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    rsis[period] = to_rsi(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rsis[i] = to_rsi(avg_gain, avg_loss)
    return rsis


def fmt(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, BOGOTA).strftime("%Y-%m-%d %H:%M")


def main():
    kl = fetch_klines()
    # Usamos solo velas CERRADAS (la ultima de Binance esta en formacion)
    closed = kl[:-1]
    opens_time = [k[0] for k in closed]
    highs = [float(k[2]) for k in closed]
    lows = [float(k[3]) for k in closed]
    closes = [float(k[4]) for k in closed]

    rsi = rsi_wilder(closes, RSI_PERIOD)

    # Marcar cada vela segun la zona en la que estuvo el RSI
    zonas = []  # (idx, zona, rsi_value)
    for i in range(len(rsi)):
        cur = rsi[i]
        if cur is None:
            continue
        if cur <= OVERSOLD:
            zonas.append((i, "SOBREVENTA", cur))
        elif cur >= OVERBOUGHT:
            zonas.append((i, "SOBRECOMPRA", cur))

    print("=" * 60)
    print(f"  {SYMBOL}  |  RSI({RSI_PERIOD}) 1H  |  Binance Futures")
    print(f"  Sobreventa: RSI <= {OVERSOLD}   |   Sobrecompra: RSI >= {OVERBOUGHT}")
    print(f"  Hora: Bogota (UTC-5), 24H")
    print("=" * 60)

    last_closed_idx = len(closes) - 1
    rsi_now = rsi[last_closed_idx]
    print(f"Vela cerrada mas reciente : {fmt(opens_time[last_closed_idx])}")
    print(f"RSI actual                : {rsi_now:.2f}")
    estado = "SOBREVENTA" if rsi_now <= OVERSOLD else \
             "SOBRECOMPRA" if rsi_now >= OVERBOUGHT else "NEUTRAL"
    print(f"Estado actual             : {estado}")
    print("-" * 60)

    if not zonas:
        print("El RSI no estuvo en ninguna zona en el historial descargado.")
        return

    idx, zona, val = zonas[-1]
    velas_atras = last_closed_idx - idx
    if velas_atras == 0:
        cuando_txt = "AHORA MISMO (vela cerrada actual)"
    else:
        cuando_txt = f"{fmt(opens_time[idx])}  ({velas_atras} velas atras)"
    print(f">> ULTIMO LUGAR DONDE ESTUVO EL RSI: {zona}")
    print(f"   Cuando : {cuando_txt}")
    print(f"   RSI en ese momento: {val:.2f}")
    print(f"   Precio close: {closes[idx]:.2f}")
    print("-" * 60)

    # Tramo de la sobre-zona: desde el toque (RSI<=30 o >=70) extendemos hacia
    # adelante y hacia atras mientras el RSI no se haya "recuperado", para
    # capturar el extremo REAL de precio (que suele formarse despues del RSI).
    if zona == "SOBREVENTA":
        sin_recuperar = lambda c: c is not None and c < RECOVERY
    else:
        sin_recuperar = lambda c: c is not None and c > (100 - RECOVERY)

    ini = idx
    while ini - 1 >= 0 and sin_recuperar(rsi[ini - 1]):
        ini -= 1
    fin = idx
    while fin + 1 <= last_closed_idx and sin_recuperar(rsi[fin + 1]):
        fin += 1

    n_velas = fin - ini + 1
    if zona == "SOBREVENTA":
        extremo_val = min(lows[ini:fin + 1])
        extremo_idx = ini + lows[ini:fin + 1].index(extremo_val)
        etq = "PRECIO MINIMO que dejo la sobreventa (low)"
    else:
        extremo_val = max(highs[ini:fin + 1])
        extremo_idx = ini + highs[ini:fin + 1].index(extremo_val)
        etq = "PRECIO MAXIMO que dejo la sobrecompra (high)"

    print(f"Tramo de {zona} (RSI sin recuperar > {RECOVERY}): {n_velas} velas")
    print(f"   Desde {fmt(opens_time[ini])}  hasta  {fmt(opens_time[fin])}")
    print(f">> {etq}: {extremo_val:.2f}")
    print(f"   Alcanzado en: {fmt(opens_time[extremo_idx])}  (RSI={rsi[extremo_idx]:.2f})")
    print("-" * 60)
    print("Velas del tramo:")
    for i in range(ini, fin + 1):
        mark = "  <-- toque RSI<=30" if rsi[i] <= OVERSOLD else ("  <== MINIMO" if i == extremo_idx else "")
        print(f"   {fmt(opens_time[i])}  RSI={rsi[i]:5.2f}  low={lows[i]:.2f}  high={highs[i]:.2f}  close={closes[i]:.2f}{mark}")


if __name__ == "__main__":
    main()
