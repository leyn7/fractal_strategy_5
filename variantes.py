"""
Compara variantes del sistema sobre la data local de 2025, para ver cual
mejora el resultado (el diagnostico mostro que el runner D va 0/7).

Variantes (runner_rr, r2_mode):
  - Completo        : 10R, full   (baseline)
  - Sin D           : 10R, cover  (Ronda 2 solo cobertura)
  - Sin Ronda 2     : 10R, none
  - Runner 5R       :  5R, full
  - Runner 3R       :  3R, full
  - Runner 3R sin D :  3R, cover

Usa la misma data y net_R (despues de comisiones) que backtest_1y.
"""
import backtest_1y as b
import backtest_disparos as bt

CONFIGS = [
    ("Completo",        10, "full"),
    ("Sin D",           10, "cover"),
    ("Sin Ronda 2",     10, "none"),
    ("Runner 5R",        5, "full"),
    ("Runner 3R",        3, "full"),
    ("Runner 3R sin D",  3, "cover"),
]


def main():
    print("Cargando data...", flush=True)
    ot1, hi1, lo1, cl1 = b.cargar_1h()
    ot3, hi3, lo3 = b.cargar_3m_desde_1m()
    anc = [(p, t) for p, t in b.anclas(ot1, lo1, cl1) if ot3[0] <= t <= ot3[-1]]
    setups = []
    for aprice, atime in anc:
        win = [k for k in range(len(ot3)) if atime <= ot3[k] < atime + 3600000]
        if win:
            setups.append((aprice, min(win, key=lambda k: lo3[k])))

    print("=" * 74)
    print(f"  VARIANTES sobre 2025  |  {len(setups)} sobreventas  |  R%>=0.5  tope F4")
    print("=" * 74)
    print(f"  {'variante':<16} {'oper':>4} {'inval':>5} {'win%':>5} "
          f"{'bruto':>8} {'NETO':>8} {'exp/trade':>9}")
    print("  " + "-" * 66)

    for nombre, rr, mode in CONFIGS:
        n_op = n_inv = wins = 0
        g = net = 0.0
        for aprice, aidx in setups:
            r = bt.correr_setup(hi3, lo3, ot3, aprice, aidx, verbose=False,
                                min_r_pct=0.5, max_fase=4,
                                runner_rr=rr, r2_mode=mode)
            if not r["operado"]:
                continue
            n_op += 1
            nr = b.net_R(r)
            g += r["realizado_R"]
            net += nr
            if "INVALIDADO" in r["estado"]:
                n_inv += 1
            if nr > 0:
                wins += 1
        wr = (wins / n_op * 100) if n_op else 0
        exp = (net / n_op) if n_op else 0
        print(f"  {nombre:<16} {n_op:>4} {n_inv:>5} {wr:>4.0f}% "
              f"{g:>+7.2f}R {net:>+7.2f}R {exp:>+8.2f}R")
    print("  " + "-" * 66)


if __name__ == "__main__":
    main()
