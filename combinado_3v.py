"""
Estrategia COMBINADA sobre data local 2025:
  Gatillo (RSI 1H): la 3a o 4a visita a una zona.
    - 3a/4a visita a SOBREVENTA  -> estrategia de fases en COMPRA (largo)
    - 3a/4a visita a SOBRECOMPRA -> estrategia de fases en VENTA (corto, espejo)
  Sobre cada gatillo se corre el sistema de fases/disparos (min_fase=1).

El corto reutiliza la maquinaria larga espejeando el precio:
  high' = -low,  low' = -high,  ancla' = -maximo.
"""
import argparse
from datetime import datetime, timezone, timedelta

import backtest_1y as b
import backtest_disparos as bt

LO, MID, HI = 30, 50, 70
VISITAS_OK = {3, 4}          # solo gatillamos en la 3a y 4a visita
BOG = timezone(timedelta(hours=-5))
# config del sistema de fases
CFG = dict(min_r_pct=0.5, max_fase=4, runner_rr=10, r2_mode="cover", min_fase=1)


def visitas_zona(rsi, ext, times, baja):
    """Detecta visitas a una zona. baja=True -> sobreventa (RSI<=LO, extremo=
    min de 'ext'); baja=False -> sobrecompra (RSI>=HI, extremo=max de 'ext').
    Una visita = tramo continuo de RSI del lado de la zona respecto a MID que
    toca el extremo. Resetea el contador cuando el RSI llega a la zona opuesta.
    Devuelve [(num_visita, precio_extremo, t_extremo)]."""
    out = []
    n = len(rsi)
    i = 0
    count = 0
    while i < n:
        x = rsi[i]
        if x is None:
            i += 1
            continue
        dentro = (x < MID) if baja else (x > MID)
        if dentro:
            j = i
            toco = False
            best = None
            best_t = None
            while j < n and (rsi[j] is None or
                             ((rsi[j] < MID) if baja else (rsi[j] > MID))):
                if rsi[j] is not None:
                    if (rsi[j] <= LO) if baja else (rsi[j] >= HI):
                        toco = True
                    v = ext[j]
                    if best is None or (v < best if baja else v > best):
                        best, best_t = v, times[j]
                j += 1
            if toco:
                count += 1
                out.append((count, best, best_t))
            i = j
        else:
            # del lado opuesto: si llega a la zona contraria, resetea secuencia
            if (x >= HI) if baja else (x <= LO):
                count = 0
            i += 1
    return out


def localizar_3m(atime, ot3, serie, buscar_min):
    win = [k for k in range(len(ot3)) if atime <= ot3[k] < atime + 3600000]
    if not win:
        return None
    return min(win, key=lambda k: serie[k]) if buscar_min \
        else max(win, key=lambda k: serie[k])


def agrupar(resultados):
    n_op = sum(1 for r in resultados if r["operado"])
    n_inv = sum(1 for r in resultados if "INVALIDADO" in r["estado"])
    g = sum(r["realizado_R"] for r in resultados if r["operado"])
    net = sum(b.net_R(r) for r in resultados if r["operado"])
    wins = sum(1 for r in resultados if r["operado"] and b.net_R(r) > 0)
    return n_op, n_inv, g, net, wins


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--visitas", default="3,4",
                    help="que numeros de visita gatillan (ej. 3,4)")
    args = ap.parse_args()
    visitas_ok = set(int(v) for v in args.visitas.split(","))

    ot1, hi1, lo1, cl1 = b.cargar_1h()
    rsi1 = b.r1.rsi_wilder(cl1, 14)
    ot3, hi3, lo3 = b.cargar_3m_desde_1m()
    mhi3 = [-v for v in lo3]      # espejo para el corto
    mlo3 = [-v for v in hi3]

    # Gatillos
    v_os = visitas_zona(rsi1, lo1, ot1, baja=True)     # sobreventa -> largo
    v_ob = visitas_zona(rsi1, hi1, ot1, baja=False)    # sobrecompra -> corto

    largos, cortos = [], []
    for num, price, t in v_os:
        if num in visitas_ok and ot3[0] <= t <= ot3[-1]:
            aidx = localizar_3m(t, ot3, lo3, buscar_min=True)
            if aidx is not None:
                largos.append(bt.correr_setup(hi3, lo3, ot3, price, aidx,
                                              verbose=False, **CFG))
    for num, price, t in v_ob:
        if num in visitas_ok and ot3[0] <= t <= ot3[-1]:
            aidx = localizar_3m(t, ot3, hi3, buscar_min=False)
            if aidx is not None:
                cortos.append(bt.correr_setup(mhi3, mlo3, ot3, -price, aidx,
                                              verbose=False, **CFG))

    desde = datetime.fromtimestamp(ot3[0] / 1000, BOG).strftime("%Y-%m-%d")
    hasta = datetime.fromtimestamp(ot3[-1] / 1000, BOG).strftime("%Y-%m-%d")
    print("=" * 70)
    print(f"  COMBINADO 3v + FASES  |  {desde} -> {hasta}  |  visitas {sorted(visitas_ok)}")
    print(f"  config: {CFG}")
    print("=" * 70)
    print(f"  gatillos sobreventa(largo): {len(v_os)} visitas, "
          f"{len(largos)} operables | sobrecompra(corto): {len(v_ob)} visitas, "
          f"{len(cortos)} operables")
    print("-" * 70)
    print(f"  {'lado':<8} {'oper':>4} {'inval':>5} {'win%':>5} {'bruto':>8} {'NETO':>8}")
    print("  " + "-" * 50)
    tg = tn = 0.0
    for nombre, res in [("LARGO", largos), ("CORTO", cortos)]:
        n_op, n_inv, g, net, wins = agrupar(res)
        wr = wins / n_op * 100 if n_op else 0
        tg += g; tn += net
        print(f"  {nombre:<8} {n_op:>4} {n_inv:>5} {wr:>4.0f}% {g:>+7.2f}R {net:>+7.2f}R")
    print("  " + "-" * 50)
    print(f"  {'TOTAL':<8} {'':>4} {'':>5} {'':>5} {tg:>+7.2f}R {tn:>+7.2f}R")


if __name__ == "__main__":
    main()
