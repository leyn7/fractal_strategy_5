"""
Analisis de comisiones (Binance USDT-M Futures) sobre el sistema de disparos.

Idea clave: la rentabilidad EN % NO depende del tamano de la posicion
(la comision es un % fijo del nocional y la ganancia 1.5R/10R tambien).
Lo que decide si vale la pena es:
  1) El minimo del exchange (para poder abrir).
  2) El "edge" del setup = R en %, frente a la comision ida+vuelta.

Comisiones VIP0 USDT-M (estandar):  maker 0.02% | taker 0.05%  (-10% con BNB).
Nuestros tipos de orden:
  - Ronda 1 (A,B): entrada LIMIT (maker).   Ronda 2 (C,D): entrada MARKET (taker).
  - TP: LIMIT (maker).   SL: STOP-MARKET (taker).
"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta

import backtest_disparos as bt
import multi_setup as ms

MK = 0.02            # maker %  (VIP0)
TK = 0.05            # taker %  (VIP0)
BNB_OFF = 0.10       # descuento pagando fees con BNB
USAR_BNB = False

ENTRY_TAKER = [False, False, True, True]   # A, B (limit) ; C, D (market)


def specs():
    info = json.loads(urllib.request.urlopen(
        "https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=20).read())
    s = next(x for x in info["symbols"] if x["symbol"] == "BNBUSDT")
    f = {ft["filterType"]: ft for ft in s["filters"]}
    min_qty = float(f["LOT_SIZE"]["minQty"])
    min_notional = float(f["MIN_NOTIONAL"]["notional"])
    price = float(json.loads(urllib.request.urlopen(
        "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BNBUSDT",
        timeout=20).read())["price"])
    return min_qty, min_notional, price


def fee_rt(entry_taker, exit_taker, bnb=USAR_BNB):
    f = (TK if entry_taker else MK) + (TK if exit_taker else MK)
    return f * (1 - BNB_OFF) if bnb else f      # % del nocional, ida+vuelta


def main():
    min_qty, min_notional, price = specs()
    piso = max(min_notional, min_qty * price)
    print("=" * 68)
    print("  COMISIONES BINANCE USDT-M FUTURES (BNBUSDT)")
    print("=" * 68)
    print(f"  Fees VIP0:  maker {MK}%  |  taker {TK}%   (-10% pagando con BNB)")
    print(f"  Minimo del exchange:  minQty={min_qty} BNB  |  MIN_NOTIONAL={min_notional} USDT")
    print(f"  Precio actual: {price:.2f}  ->  POSICION MINIMA = {min_qty} BNB ~= {piso:.2f} USDT")
    print("-" * 68)
    print("  Comision ida+vuelta segun tipo de orden:")
    print(f"     LIMIT entry + LIMIT TP   (maker+maker) = {fee_rt(False, False):.3f}%")
    print(f"     LIMIT entry + STOP SL    (maker+taker) = {fee_rt(False, True):.3f}%")
    print(f"     MARKET entry + LIMIT TP  (taker+maker) = {fee_rt(True, False):.3f}%")
    print(f"     MARKET entry + STOP SL   (taker+taker) = {fee_rt(True, True):.3f}%")
    print("=" * 68)
    print("  CONCEPTO: la rentabilidad en % es IGUAL a cualquier tamano.")
    print("  El tamano minimo para 'poder operar' es el del exchange (arriba).")
    print("  Lo que define si VALE LA PENA es el R% del setup vs la comision.")
    print("=" * 68)

    # --- Aplicar a los setups detectados ---
    anclas = ms.anclas_sobreventa(7)
    start_ms = min(t for _, t in anclas) - 3600 * 1000
    kl3 = bt.fetch_3m(datetime.fromtimestamp(start_ms / 1000, timezone.utc))[:-1]
    ot3 = [k[0] for k in kl3]
    hi3 = [float(k[2]) for k in kl3]
    lo3 = [float(k[3]) for k in kl3]

    print("  SETUPS (ultimos 7 dias): bruto vs neto despues de comisiones")
    print(f"  {'ancla':>8} {'R%':>6} {'feeR(mm)':>9} {'bruto':>8} {'fees':>7} {'neto':>8}  estado")
    print("  " + "-" * 64)
    tot_bruto = tot_neto = 0.0
    for aprice, atime in anclas:
        win = [k for k in range(len(ot3)) if atime <= ot3[k] < atime + 3600000]
        if not win:
            continue
        aidx = min(win, key=lambda k: lo3[k])
        r = bt.correr_setup(hi3, lo3, ot3, aprice, aidx, verbose=False)
        if not r["operado"]:
            print(f"  {aprice:>8.2f} {'--':>6} {'--':>9} {'--':>8} {'--':>7} {'--':>8}  {r['estado']}")
            continue
        rpct = r["R_pct"]
        fees_R = 0.0
        for k, est in enumerate(r["disparos"]):
            if est == "ABIERTA":
                continue
            fees_R += fee_rt(ENTRY_TAKER[k], est.startswith("STOP")) / rpct
        neto = r["realizado_R"] - fees_R
        tot_bruto += r["realizado_R"]
        tot_neto += neto
        feemm = fee_rt(False, False) / rpct   # fee de un disparo maker/maker en R
        print(f"  {aprice:>8.2f} {rpct:>5.2f}% {feemm:>8.3f}R {r['realizado_R']:>+7.2f}R "
              f"{-fees_R:>+6.2f}R {neto:>+7.2f}R  {r['estado']}")
    print("  " + "-" * 64)
    print(f"  COMBINADO:  bruto {tot_bruto:+.2f}R   ->   NETO {tot_neto:+.2f}R")
    print("  (no incluye comisiones de los runners aun abiertos)")


if __name__ == "__main__":
    main()
