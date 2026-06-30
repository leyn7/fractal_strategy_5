"""
Modo MULTI-SETUP automatico.

Regla: cada sobreventa del RSI 1H (cada minimo de un tramo RSI<=30) es un
ancla independiente. Por cada ancla se lanza el setup completo (fases 3m +
4 disparos) y se corren EN PARALELO. Cada setup se cancela solo si el precio
vuelve a SU propia ancla (0%). Al final se combina el resultado.

Reutiliza la logica de backtest_disparos.py y rsi_1h_signal.py.
"""
import argparse
from datetime import datetime, timezone, timedelta

import backtest_disparos as bt
import rsi_1h_signal as r1

OVERSOLD = 30
RECOVERY = 40            # RSI debe recuperarse > 40 para cerrar el tramo
BOG = timezone(timedelta(hours=-5))


def fmt(ts):
    return datetime.fromtimestamp(ts / 1000, BOG).strftime("%m-%d %H:%M")


def anclas_sobreventa(dias):
    """Devuelve [(precio_min, ts_min)] de cada tramo de sobreventa RSI 1H
    cuyo minimo cae dentro de los ultimos `dias`."""
    kl = r1.fetch_klines()[:-1]            # 1H cerradas
    ot = [k[0] for k in kl]
    lo = [float(k[3]) for k in kl]
    cl = [float(k[4]) for k in kl]
    rsi = r1.rsi_wilder(cl, 14)
    corte = ot[-1] - dias * 24 * 3600 * 1000
    anclas = []
    i, n = 0, len(cl)
    while i < n:
        if rsi[i] is not None and rsi[i] < RECOVERY:
            j = i
            while j + 1 < n and rsi[j + 1] is not None and rsi[j + 1] < RECOVERY:
                j += 1
            if min(rsi[i:j + 1]) <= OVERSOLD:
                mn = min(lo[i:j + 1])
                mni = i + lo[i:j + 1].index(mn)
                if ot[mni] >= corte:
                    anclas.append((mn, ot[mni]))
            i = j + 1
        else:
            i += 1
    return anclas


def main():
    ap = argparse.ArgumentParser(description="Multi-setup automatico")
    ap.add_argument("--days", type=int, default=7,
                    help="ventana (dias) para buscar sobreventas")
    args = ap.parse_args()

    anclas = anclas_sobreventa(args.days)
    if not anclas:
        print("No hay anclas de sobreventa en el periodo.")
        return

    # 3m desde la sobreventa mas antigua (con 1h de margen) hasta ahora
    start_ms = min(t for _, t in anclas) - 3600 * 1000
    kl3 = bt.fetch_3m(datetime.fromtimestamp(start_ms / 1000, timezone.utc))[:-1]
    ot3 = [k[0] for k in kl3]
    hi3 = [float(k[2]) for k in kl3]
    lo3 = [float(k[3]) for k in kl3]

    print("#" * 70)
    print(f"  MULTI-SETUP  |  {len(anclas)} sobreventas RSI 1H (ultimos {args.days} dias)")
    print("#" * 70)

    resumen = []
    for aprice, atime in anclas:
        print("\n" + "#" * 70)
        print(f"### ANCLA {aprice:.2f}   (sobreventa 1H: {fmt(atime)})")
        print("#" * 70)
        win = [k for k in range(len(ot3)) if atime <= ot3[k] < atime + 3600000]
        if not win:
            print("  (sin datos 3m para esta ancla)")
            continue
        aidx = min(win, key=lambda k: lo3[k])   # vela 3m del minimo
        res = bt.correr_setup(hi3, lo3, ot3, aprice, aidx, verbose=True)
        resumen.append((aprice, atime, res))

    # ---------- RESUMEN COMBINADO ----------
    print("\n" + "=" * 70)
    print("  RESUMEN COMBINADO (todos los setups en paralelo)")
    print("=" * 70)
    print(f"  {'ancla':>8}  {'sobreventa':>12}  {'fases':>5}  {'realizado':>10}  estado")
    print("  " + "-" * 64)
    total = 0.0
    abiertos = 0
    operados = 0
    for aprice, atime, res in resumen:
        total += res["realizado_R"]
        if res["abierta"]:
            abiertos += 1
        if res["operado"]:
            operados += 1
        rstr = f"{res['realizado_R']:+.2f}R" if res["operado"] else "--"
        print(f"  {aprice:>8.2f}  {fmt(atime):>12}  {res['n_fases']:>5}  "
              f"{rstr:>10}  {res['estado']}")
    print("  " + "-" * 64)
    print(f"  Setups operados: {operados}/{len(resumen)}   |   con posiciones abiertas: {abiertos}")
    print(f"  >> REALIZADO COMBINADO: {total:+.2f} R")
    print("     (los runners abiertos no suman hasta cerrarse)")


if __name__ == "__main__":
    main()
