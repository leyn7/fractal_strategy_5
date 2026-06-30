"""
Backtest profundo (~2025) usando data historica local:
  - 1H: BNBUSDT_1h_20240101_20260615.csv  (RSI / anclas de sobreventa)
  - 1m: BNBUSDT_1m_2025.csv  -> resampleado a 3m (high=max, low=min)

Aplica el sistema completo (filtro R% >= 0.5%, tope F4) sobre cada
sobreventa del periodo y reporta estadisticas agregadas, bruto y NETO
(despues de comisiones Binance VIP0).
"""
import argparse
import csv
from datetime import datetime, timezone, timedelta

import backtest_disparos as bt
import rsi_1h_signal as r1

DATA = r"C:\Users\leyner\Documents\proyectos\trading\binance\historical_data"
CSV_1H = DATA + r"\klines_1h\BNBUSDT_1h_20240101_20260615.csv"
CSV_1M = DATA + r"\BNBUSDT_1m_2025.csv"

OVERSOLD, RECOVERY, MIN_R, MAX_FASE = 30, 40, 0.5, 4
MK, TK = 0.02, 0.05                    # fees VIP0 %
ENTRY_TAKER = [False, False, True, True]
BOG = timezone(timedelta(hours=-5))


def to_ms(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
               .replace(tzinfo=timezone.utc).timestamp() * 1000)


def cargar_1h():
    ot, hi, lo, cl = [], [], [], []
    with open(CSV_1H, newline="") as f:
        rd = csv.reader(f)
        next(rd)
        for row in rd:
            ot.append(to_ms(row[0]))
            hi.append(float(row[2]))
            lo.append(float(row[3]))
            cl.append(float(row[4]))
    return ot, hi, lo, cl


def cargar_3m_desde_1m():
    """Resamplea el 1m a 3m: bucket = floor(ts / 3min)."""
    buckets = {}
    with open(CSV_1M, newline="") as f:
        rd = csv.reader(f)
        next(rd)
        for row in rd:
            ts = to_ms(row[0])
            h, l = float(row[1]), float(row[2])
            b = (ts // 180000) * 180000
            if b in buckets:
                if h > buckets[b][0]:
                    buckets[b][0] = h
                if l < buckets[b][1]:
                    buckets[b][1] = l
            else:
                buckets[b] = [h, l]
    keys = sorted(buckets)
    ot = keys
    hi = [buckets[k][0] for k in keys]
    lo = [buckets[k][1] for k in keys]
    return ot, hi, lo


def anclas(ot, lo, cl):
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
    if not res["operado"]:
        return 0.0
    fees = 0.0
    for k, est in enumerate(res["disparos"]):
        if est == "ABIERTA":
            continue
        e = (TK if ENTRY_TAKER[k] else MK)
        x = (TK if est.startswith("STOP") else MK)
        fees += (e + x) / res["R_pct"]
    return res["realizado_R"] - fees


def main():
    print("Cargando 1H...", end=" ", flush=True)
    ot1, hi1, lo1, cl1 = cargar_1h()
    print(f"{len(ot1)} velas. Resampleando 1m->3m...", end=" ", flush=True)
    ot3, hi3, lo3 = cargar_3m_desde_1m()
    print(f"{len(ot3)} velas 3m.")
    lo3_min, lo3_max_t = ot3[0], ot3[-1]

    anc = [(p, t) for p, t in anclas(ot1, lo1, cl1) if ot3[0] <= t <= ot3[-1]]
    desde = datetime.fromtimestamp(ot3[0] / 1000, BOG).strftime("%Y-%m-%d")
    hasta = datetime.fromtimestamp(ot3[-1] / 1000, BOG).strftime("%Y-%m-%d")
    print("=" * 72)
    print(f"  BACKTEST PROFUNDO  |  {desde}  ->  {hasta}  (Bogota)")
    print(f"  {len(anc)} sobreventas RSI 1H  |  filtro R%>={MIN_R}%  tope F{MAX_FASE}")
    print("=" * 72)

    n_op = n_inv = wins = losses = abiertos = 0
    g = net = 0.0
    detalle = []
    for aprice, atime in anc:
        win = [k for k in range(len(ot3)) if atime <= ot3[k] < atime + 3600000]
        if not win:
            continue
        aidx = min(win, key=lambda k: lo3[k])
        r = bt.correr_setup(hi3, lo3, ot3, aprice, aidx,
                            verbose=False, min_r_pct=MIN_R, max_fase=MAX_FASE)
        if not r["operado"]:
            continue
        n_op += 1
        nr = net_R(r)
        g += r["realizado_R"]
        net += nr
        if "INVALIDADO" in r["estado"]:
            n_inv += 1
        if r["abierta"]:
            abiertos += 1
        if nr > 0:
            wins += 1
        elif nr < 0:
            losses += 1
        detalle.append((atime, aprice, r["fase_operada"], r["R_pct"],
                        r["realizado_R"], nr, r["estado"]))

    print(f"  {'fecha':>12} {'ancla':>8} {'fase':>4} {'R%':>5} {'bruto':>7} {'neto':>7}  estado")
    print("  " + "-" * 68)
    for atime, aprice, fase, rpct, br, nr, est in detalle:
        fch = datetime.fromtimestamp(atime / 1000, BOG).strftime("%m-%d %H:%M")
        print(f"  {fch:>12} {aprice:>8.2f}  F{fase:<2} {rpct:>4.2f}% {br:>+6.2f}R "
              f"{nr:>+6.2f}R  {est[:26]}")
    print("  " + "-" * 68)
    wr = (wins / n_op * 100) if n_op else 0
    print(f"  Operados: {n_op}  |  invalidados: {n_inv}  |  abiertos: {abiertos}")
    print(f"  Ganadores: {wins}  perdedores: {losses}  ->  win-rate {wr:.0f}%")
    print(f"  R BRUTO: {g:+.2f}R     R NETO (tras comisiones): {net:+.2f}R")
    if n_op:
        print(f"  Expectativa por trade: {net / n_op:+.2f}R neto")


if __name__ == "__main__":
    main()
