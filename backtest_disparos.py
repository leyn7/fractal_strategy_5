"""
Backtest del sistema de 4 disparos (francotirador) sobre BNBUSDT 3m.

Fibo CONGELADO en la Fase 3 (ancla = minimo penultima sobreventa).
  Ronda 1 (entra en 50%, SL en 25%):
     A cobertura  -> TP +1.5R
     B runner     -> TP +10R   (mantiene su SL en 25%)
  Ronda 2 (se dispara en 25% cuando B se cierra por stop; SL en 0%=ancla):
     C cobertura  -> TP +1.5R
     D runner     -> TP +10R
  Si el precio toca el 0% (ancla) en ronda 2 -> invalidacion: cierra todo.

Supuestos:
  - Entrada de ronda 1 = vela que completa la Fase 3 (toque del 50%).
  - Dentro de una vela, si caben SL y TP, se asume SL primero (conservador).
  - Cada disparo arriesga 1R. P&L en multiplos de R.
"""
import json
import argparse
import urllib.request
from datetime import datetime, timezone, timedelta

SYMBOL = "BNBUSDT"
INTERVAL = "3m"
ANCHOR = 540.50  # default: minimo de la penultima sobreventa
START_UTC = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
FACTOR_150 = 1.5
BOGOTA = timezone(timedelta(hours=-5))


def fetch_3m(start_dt):
    start_ms = int(start_dt.timestamp() * 1000)
    out = []
    while True:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL}"
               f"&interval={INTERVAL}&startTime={start_ms}&limit=1500")
        with urllib.request.urlopen(url, timeout=20) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1500:
            break
        start_ms = batch[-1][0] + 1
    return out


def fmt(ts):
    return datetime.fromtimestamp(ts / 1000, BOGOTA).strftime("%m-%d %H:%M")


def detectar_fases(hi, lo, ot, anchor, start):
    """Devuelve lista de fases: (idx_toque_50, techo, idx_techo)."""
    running_max = anchor
    prev_techo = anchor
    armed = True
    fases = []
    techo_idx = start
    for i in range(start, len(hi)):
        h, l = hi[i], lo[i]
        if l < anchor:
            break
        new_high = h > running_max
        if new_high:
            running_max = h
            techo_idx = i
        if len(fases) >= 1:
            cap = prev_techo + FACTOR_150 * (prev_techo - anchor)
            if running_max > cap:
                break
        if not armed and running_max > prev_techo:
            armed = True
        level50 = (anchor + running_max) / 2.0
        if armed and not new_high and running_max > prev_techo and l <= level50:
            fases.append((i, running_max, techo_idx))
            prev_techo = running_max
            armed = False
    return fases


def armar_entrada_75(hi, lo, ot, anchor, start, techo_fase2):
    """Armado de la entrada del 50% via el 75% (solo Ronda 1, 3a fase).
    - Mientras se forma el 3er techo (trailing), si el precio toca el 75%
      se coloca una orden limite en el 50%.
    - Si el precio hace un maximo nuevo, se cancela (el techo subio).
    - Cuando el low toca el 50% con orden colocada -> FILL (entrada A/B).
    Devuelve (entry_idx, entry_price, eventos) o (None, None, eventos)."""
    running_techo = techo_fase2
    order_level = None
    eventos = []
    for i in range(start, len(hi)):
        h, l = hi[i], lo[i]
        if l < anchor:
            eventos.append((i, "INVALIDA (rompio 0%)", anchor))
            return None, None, eventos
        if h > running_techo:                       # maximo nuevo -> techo sube
            running_techo = h
            if order_level is not None:
                eventos.append((i, "CANCELA orden 50%", order_level))
                order_level = None
            continue
        if running_techo <= techo_fase2:            # aun no rompe techo fase 2
            continue
        lvl75 = anchor + 0.75 * (running_techo - anchor)
        lvl50 = anchor + 0.50 * (running_techo - anchor)
        if order_level is None and l <= lvl75:      # pullback al 75% -> coloca
            order_level = lvl50
            eventos.append((i, "COLOCA orden 50%", lvl50))
        if order_level is not None and l <= order_level:  # toca 50% -> fill
            eventos.append((i, "FILL entrada 50%", order_level))
            return i, order_level, eventos
    return None, None, eventos


def simular(hi, lo, ot, start, entry, sl, tp_cov, tp_run, etq_cov, etq_run, r_price):
    """Simula 2 disparos (cobertura + runner) con mismo entry y SL.
    Devuelve (resultados, idx_cierre_runner, runner_stopped)."""
    cov = {"name": etq_cov, "tp": tp_cov, "rr": 1.5, "estado": "ABIERTA", "i": None}
    run = {"name": etq_run, "tp": tp_run, "rr": 10.0, "estado": "ABIERTA", "i": None}
    idx_run_close = None
    runner_stopped = False
    for i in range(start, len(hi)):
        h, l = hi[i], lo[i]
        for pos in (cov, run):
            if pos["estado"] != "ABIERTA":
                continue
            if l <= sl:                      # SL primero (conservador)
                pos["estado"] = "STOP (-1R)"
                pos["i"] = i
                if pos is run:
                    idx_run_close = i
                    runner_stopped = True
            elif h >= pos["tp"]:
                pos["estado"] = f"TP (+{pos['rr']:.1f}R)"
                pos["i"] = i
                if pos is run:
                    idx_run_close = i
        if cov["estado"] != "ABIERTA" and run["estado"] != "ABIERTA":
            break
    return cov, run, idx_run_close, runner_stopped


def pnl_de(estado):
    if estado.startswith("TP"):
        return float(estado.split("+")[1].split("R")[0])
    if estado.startswith("STOP"):
        return -1.0
    return 0.0  # abierta


def linea(pos, entry, sl, ot):
    cuando = fmt(ot[pos["i"]]) if pos["i"] is not None else "-- (sigue abierta)"
    return (f"   {pos['name']:<22} entry={entry:.2f}  SL={sl:.2f}  TP={pos['tp']:.2f}"
            f"  ->  {pos['estado']:<11} {cuando}")


def correr_setup(hi, lo, ot, anchor, anchor_idx, verbose=True, min_r_pct=0.0):
    """Corre un setup completo (fases + 4 disparos) sobre un ancla dada.
    anchor_idx = indice 3m del minimo (ancla). Devuelve dict con resultado.
    min_r_pct: si R% < umbral, el setup se descarta (fees se comen el edge)."""
    def out(*a):
        if verbose:
            print(*a)

    res = {"anchor": anchor, "n_fases": 0, "operado": False,
           "realizado_R": 0.0, "estado": "", "disparos": [], "abierta": False,
           "entry": None, "R_price": None, "R_pct": None}

    fases = detectar_fases(hi, lo, ot, anchor, anchor_idx + 1)
    res["n_fases"] = len(fases)
    if len(fases) < 3:
        res["estado"] = f"NO OPERADO ({len(fases)} fases; faltan {3 - len(fases)})"
        out(res["estado"])
        return res

    # Fibo congelado en la FASE 3
    _, techo, _ = fases[2]
    leg = techo - anchor
    lvl50 = anchor + 0.50 * leg
    lvl25 = anchor + 0.25 * leg
    R = lvl50 - lvl25
    res["entry"] = lvl50
    res["R_price"] = R
    res["R_pct"] = R / lvl50 * 100.0
    out("=" * 70)
    out(f"  FIBO CONGELADO EN FASE 3  |  ancla={anchor:.2f}  techo={techo:.2f}")
    out(f"  0%={anchor:.2f}  25%={lvl25:.2f}  50%={lvl50:.2f}  75%="
        f"{anchor + 0.75 * leg:.2f}  100%={techo:.2f}  R={R:.2f}  (R%={res['R_pct']:.2f}%)")
    out("=" * 70)

    # Filtro de edge: si el R% es muy chico, las comisiones se lo comen
    if res["R_pct"] < min_r_pct:
        res["estado"] = f"FILTRADO (R%={res['R_pct']:.2f}% < {min_r_pct:.2f}%)"
        out(">> " + res["estado"] + " -> no se opera")
        return res

    # Armado de la entrada por el 75%
    entry_idx, entry_price, eventos = armar_entrada_75(
        hi, lo, ot, anchor, fases[1][0] + 1, fases[1][1])
    out("ARMADO (75% -> coloca/cancela orden en 50%):")
    for i, ev, px in eventos:
        out(f"   {fmt(ot[i])}  {ev:<22} @ {px:.2f}")
    if entry_idx is None:
        res["estado"] = "ARMADA pero la entrada del 50% no se lleno (o invalido)"
        out(">> " + res["estado"])
        return res
    out(f">> ENTRADA LLENA en 50%={entry_price:.2f}  ({fmt(ot[entry_idx])})")
    out("=" * 70)

    res["operado"] = True
    total_R = 0.0

    # Ronda 1
    cov, run, idx_run_close, runner_stop = simular(
        hi, lo, ot, entry_idx + 1, lvl50, lvl25,
        lvl50 + 1.5 * R, lvl50 + 10.0 * R,
        "A cobertura (1:1.5)", "B runner (1:10)", R)
    out("RONDA 1  (entry 50%, SL 25%):")
    out(linea(cov, lvl50, lvl25, ot))
    out(linea(run, lvl50, lvl25, ot))
    for p in (cov, run):
        res["disparos"].append(p["estado"])
        if p["estado"] == "ABIERTA":
            res["abierta"] = True
    total_R += pnl_de(cov["estado"]) + pnl_de(run["estado"])

    # Ronda 2 (market al cerrarse la Ronda 1, solo si B se fue al stop)
    if runner_stop:
        entry2, sl2 = lvl25, anchor
        R2 = entry2 - sl2
        out("-" * 70)
        out(f"RONDA 2  (MARKET al cerrarse Ronda 1; entra ~{entry2:.2f}, "
            f"SL 0%={sl2:.2f}, R={R2:.2f}):")
        covC, runD, _, d_stop = simular(
            hi, lo, ot, idx_run_close + 1, entry2, sl2,
            entry2 + 1.5 * R2, entry2 + 10.0 * R2,
            "C cobertura (1:1.5)", "D runner (1:10)", R2)
        out(linea(covC, entry2, sl2, ot))
        out(linea(runD, entry2, sl2, ot))
        for p in (covC, runD):
            res["disparos"].append(p["estado"])
            if p["estado"] == "ABIERTA":
                res["abierta"] = True
        total_R += pnl_de(covC["estado"]) + pnl_de(runD["estado"])
        if d_stop:
            res["estado"] = f"INVALIDADO: el precio toco el 0% ({anchor:.2f})"
            out("   >> " + res["estado"])
    else:
        out("-" * 70)
        out("RONDA 2 no se disparo (el runner B no se cerro por stop).")

    if not res["estado"]:
        res["estado"] = "EN CURSO" if res["abierta"] else "CERRADO"
    res["realizado_R"] = total_R
    out("=" * 70)
    out(f">> RESULTADO (realizado): {total_R:+.2f} R   [{res['estado']}]")
    return res


def main():
    kl = fetch_3m(START_UTC)[:-1]
    ot = [k[0] for k in kl]
    hi = [float(k[2]) for k in kl]
    lo = [float(k[3]) for k in kl]
    anchor_idx = lo.index(min(lo))         # vela del minimo (ancla) en 3m
    correr_setup(hi, lo, ot, ANCHOR, anchor_idx, verbose=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backtest 4 disparos sobre un ancla")
    ap.add_argument("--anchor", type=float, default=ANCHOR,
                    help="precio ancla (0% del fibo)")
    ap.add_argument("--start", type=str, default=START_UTC.strftime("%Y-%m-%dT%H:%M"),
                    help="inicio de descarga 3m en UTC (YYYY-MM-DDTHH:MM)")
    args = ap.parse_args()
    ANCHOR = args.anchor
    START_UTC = datetime.strptime(args.start, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    main()
