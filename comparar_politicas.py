"""
Compara politicas de seleccion de fase sobre mas historia, para decidir si
"operar fases tardias" (cuando F3 queda filtrada por R%) conviene o no.

Politicas (parametro max_fase de correr_setup):
  - Solo F3      : opera solo si la fase 3 pasa el filtro R%.
  - F3-F4        : opera la primera fase operable, hasta la 4.
  - F3-F5        : ... hasta la 5.
  - Cualquiera   : la primera fase operable, sea la que sea.

Reporta, por politica: setups operados, invalidados, R bruto y R NETO
(despues de comisiones), sobre todas las sobreventas del periodo.
"""
import argparse
import json
import urllib.request
from datetime import datetime, timezone, timedelta

import backtest_disparos as bt
import rsi_1h_signal as r1
import comisiones as com

OVERSOLD, RECOVERY = 30, 40
MIN_R = 0.5


def fetch_1h(start_dt):
    start_ms = int(start_dt.timestamp() * 1000)
    out = []
    while True:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol=BNBUSDT"
               f"&interval=1h&startTime={start_ms}&limit=1500")
        batch = json.loads(urllib.request.urlopen(url, timeout=20).read())
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1500:
            break
        start_ms = batch[-1][0] + 1
    return out


def anclas(kl1h):
    kl = kl1h[:-1]
    ot = [k[0] for k in kl]
    lo = [float(k[3]) for k in kl]
    cl = [float(k[4]) for k in kl]
    rsi = r1.rsi_wilder(cl, 14)
    res = []
    i, n = 0, len(cl)
    while i < n:
        if rsi[i] is not None and rsi[i] < RECOVERY:
            j = i
            while j + 1 < n and rsi[j + 1] is not None and rsi[j + 1] < RECOVERY:
                j += 1
            if min(rsi[i:j + 1]) <= OVERSOLD:
                mn = min(lo[i:j + 1])
                res.append((mn, ot[i + lo[i:j + 1].index(mn)]))
            i = j + 1
        else:
            i += 1
    return res


def net_R(res):
    """R neto despues de comisiones de los disparos CERRADOS."""
    if not res["operado"]:
        return 0.0
    fees = 0.0
    for k, est in enumerate(res["disparos"]):
        if est == "ABIERTA":
            continue
        fees += com.fee_rt(com.ENTRY_TAKER[k], est.startswith("STOP")) / res["R_pct"]
    return res["realizado_R"] - fees


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    args = ap.parse_args()

    kl1h = fetch_1h(datetime.now(timezone.utc) - timedelta(days=args.days))
    anc = anclas(kl1h)
    start3 = min(t for _, t in anc) - 3600 * 1000
    kl3 = bt.fetch_3m(datetime.fromtimestamp(start3 / 1000, timezone.utc))[:-1]
    ot3 = [k[0] for k in kl3]
    hi3 = [float(k[2]) for k in kl3]
    lo3 = [float(k[3]) for k in kl3]

    # indice 3m del minimo de cada ancla
    setups = []
    for aprice, atime in anc:
        win = [k for k in range(len(ot3)) if atime <= ot3[k] < atime + 3600000]
        if win:
            setups.append((aprice, min(win, key=lambda k: lo3[k])))

    print("=" * 72)
    print(f"  COMPARACION DE POLITICAS  |  {len(setups)} sobreventas en {args.days} dias")
    print(f"  filtro R% >= {MIN_R}%  |  comisiones VIP0 (maker 0.02 / taker 0.05)")
    print("=" * 72)
    print(f"  {'politica':<12} {'oper':>5} {'inval':>6} {'bruto':>9} {'NETO':>9} "
          f"{'gana':>5} {'pierde':>6}")
    print("  " + "-" * 64)

    for nombre, mx in [("Solo F3", 3), ("F3-F4", 4), ("F3-F5", 5), ("Cualquiera", 99)]:
        g = n_op = n_inv = wins = losses = 0
        net_tot = 0.0
        for aprice, aidx in setups:
            r = bt.correr_setup(hi3, lo3, ot3, aprice, aidx,
                                verbose=False, min_r_pct=MIN_R, max_fase=mx)
            if not r["operado"]:
                continue
            n_op += 1
            g += r["realizado_R"]
            nr = net_R(r)
            net_tot += nr
            if "INVALIDADO" in r["estado"]:
                n_inv += 1
            if nr > 0:
                wins += 1
            elif nr < 0:
                losses += 1
        print(f"  {nombre:<12} {n_op:>5} {n_inv:>6} {g:>+8.2f}R {net_tot:>+8.2f}R "
              f"{wins:>5} {losses:>6}")
    print("  " + "-" * 64)
    print("  (R realizado; los runners abiertos al final del periodo no suman)")


if __name__ == "__main__":
    main()
