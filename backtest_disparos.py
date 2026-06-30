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


def simular(hi, lo, ot, start, entry, sl, tp_cov, tp_run, etq_cov, etq_run, r_price,
            rr_run=10.0, con_runner=True):
    """Simula la cobertura (+1.5R) y, si con_runner, un runner (+rr_run R)
    con mismo entry y SL. Devuelve (cov, run, idx_cierre_runner, runner_stopped)."""
    cov = {"name": etq_cov, "tp": tp_cov, "rr": 1.5, "estado": "ABIERTA", "i": None}
    run = {"name": etq_run, "tp": tp_run, "rr": rr_run,
           "estado": "ABIERTA" if con_runner else "N/A", "i": None}
    idx_run_close = None
    runner_stopped = False
    pos_sim = (cov, run) if con_runner else (cov,)
    for i in range(start, len(hi)):
        h, l = hi[i], lo[i]
        for pos in pos_sim:
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
        if all(p["estado"] != "ABIERTA" for p in pos_sim):
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


def correr_setup(hi, lo, ot, anchor, anchor_idx, verbose=True, min_r_pct=0.0,
                 max_fase=99, runner_rr=10.0, r2_mode="full", min_fase=3):
    """Corre un setup completo (fases + 4 disparos) sobre un ancla dada.
    anchor_idx = indice 3m del minimo (ancla). Devuelve dict con resultado.
    min_r_pct: si R% < umbral, el setup se descarta (fees se comen el edge).
    max_fase: si la primera fase operable es > max_fase, no se opera (evita
    operar fases muy tardias/agotadas).
    runner_rr: objetivo del runner (multiplo de R, default 10).
    r2_mode: 'full' (C+D) | 'cover' (solo C) | 'none' (sin Ronda 2)."""
    def out(*a):
        if verbose:
            print(*a)

    res = {"anchor": anchor, "n_fases": 0, "operado": False,
           "realizado_R": 0.0, "estado": "", "disparos": [], "abierta": False,
           "entry": None, "R_price": None, "R_pct": None, "fase_operada": None}

    fases = detectar_fases(hi, lo, ot, anchor, anchor_idx + 1)
    res["n_fases"] = len(fases)
    if len(fases) < min_fase:
        res["estado"] = f"NO OPERADO ({len(fases)} fases; faltan {min_fase - len(fases)})"
        out(res["estado"])
        return res

    # Elegir la PRIMERA fase operable (>=min_fase) cuyo R% pase el filtro.
    # El techo crece con cada fase, asi que el R% es mayor en fases posteriores:
    # si la fase min queda filtrada por R%, se prueba la siguiente, etc.
    op = None
    for p in range(min_fase - 1, len(fases)):
        leg_p = fases[p][1] - anchor
        rpct_p = (0.25 * leg_p) / (anchor + 0.50 * leg_p) * 100.0
        if rpct_p >= min_r_pct:
            op = p
            break

    if op is None:
        leg_m = fases[-1][1] - anchor      # la fase mas grande disponible
        res["R_pct"] = (0.25 * leg_m) / (anchor + 0.50 * leg_m) * 100.0
        res["estado"] = (f"FILTRADO (ninguna de {len(fases)} fases con "
                         f"R% >= {min_r_pct:.2f}%; max R%={res['R_pct']:.2f}%)")
        out(">> " + res["estado"])
        return res

    if (op + 1) > max_fase:                 # primera fase operable es muy tardia
        leg_o = fases[op][1] - anchor
        res["R_pct"] = (0.25 * leg_o) / (anchor + 0.50 * leg_o) * 100.0
        res["estado"] = (f"NO OPERADO (1a fase operable F{op + 1} > tope F{max_fase})")
        out(">> " + res["estado"])
        return res

    # Fibo congelado en la fase operable elegida
    n_fase = op + 1                        # numero de fase (1-based)
    _, techo, _ = fases[op]
    leg = techo - anchor
    lvl50 = anchor + 0.50 * leg
    lvl25 = anchor + 0.25 * leg
    R = lvl50 - lvl25
    res["entry"] = lvl50
    res["R_price"] = R
    res["R_pct"] = R / lvl50 * 100.0
    res["fase_operada"] = n_fase
    out("=" * 70)
    out(f"  FIBO CONGELADO EN FASE {n_fase}  |  ancla={anchor:.2f}  techo={techo:.2f}")
    out(f"  0%={anchor:.2f}  25%={lvl25:.2f}  50%={lvl50:.2f}  75%="
        f"{anchor + 0.75 * leg:.2f}  100%={techo:.2f}  R={R:.2f}  (R%={res['R_pct']:.2f}%)")
    if op > min_fase - 1:
        out(f"  (fases {min_fase}..{n_fase - 1} quedaron bajo el filtro R% {min_r_pct:.2f}%)")
    out("=" * 70)

    # Armado de la entrada por el 75%. La "fase previa" es la op-1; para la
    # fase 1 (op==0) la referencia previa es el propio ancla.
    if op >= 1:
        prev_idx, prev_techo = fases[op - 1][0], fases[op - 1][1]
    else:
        prev_idx, prev_techo = anchor_idx, anchor
    entry_idx, entry_price, eventos = armar_entrada_75(
        hi, lo, ot, anchor, prev_idx + 1, prev_techo)
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

    # Ronda 1  (A cobertura 1.5R, B runner runner_rr R)
    cov, run, idx_run_close, runner_stop = simular(
        hi, lo, ot, entry_idx + 1, lvl50, lvl25,
        lvl50 + 1.5 * R, lvl50 + runner_rr * R,
        "A cobertura (1:1.5)", f"B runner (1:{runner_rr:g})", R, rr_run=runner_rr)
    out("RONDA 1  (entry 50%, SL 25%):")
    out(linea(cov, lvl50, lvl25, ot))
    out(linea(run, lvl50, lvl25, ot))
    for p in (cov, run):
        res["disparos"].append(p["estado"])
        if p["estado"] == "ABIERTA":
            res["abierta"] = True
    total_R += pnl_de(cov["estado"]) + pnl_de(run["estado"])

    # Ronda 2 (market al cerrarse la Ronda 1, solo si B se fue al stop)
    if r2_mode != "none" and runner_stop:
        con_runner = (r2_mode == "full")
        entry2, sl2 = lvl25, anchor
        R2 = entry2 - sl2
        out("-" * 70)
        out(f"RONDA 2  ({r2_mode}; entra ~{entry2:.2f}, SL 0%={sl2:.2f}, R={R2:.2f}):")
        covC, runD, _, _ = simular(
            hi, lo, ot, idx_run_close + 1, entry2, sl2,
            entry2 + 1.5 * R2, entry2 + runner_rr * R2,
            "C cobertura (1:1.5)", f"D runner (1:{runner_rr:g})", R2,
            rr_run=runner_rr, con_runner=con_runner)
        out(linea(covC, entry2, sl2, ot))
        if con_runner:
            out(linea(runD, entry2, sl2, ot))
        shots2 = (covC, runD) if con_runner else (covC,)
        for p in shots2:
            res["disparos"].append(p["estado"])
            if p["estado"] == "ABIERTA":
                res["abierta"] = True
        total_R += sum(pnl_de(p["estado"]) for p in shots2)
        # invalidacion: cualquier disparo de Ronda 2 (SL en el ancla) que se detiene
        if any(p["estado"].startswith("STOP") for p in shots2):
            res["estado"] = f"INVALIDADO: el precio toco el 0% ({anchor:.2f})"
            out("   >> " + res["estado"])
    elif r2_mode == "none":
        out("-" * 70)
        out("RONDA 2 desactivada (r2_mode=none).")
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
