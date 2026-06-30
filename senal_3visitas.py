"""
Backtest de la senal "K visitas a sobreventa -> largo" (RSI 1H, BNBUSDT).

Regla:
  - Se cuentan visitas a sobreventa (RSI<=30, separadas por recuperar >50).
  - Tras la visita K, cuando el RSI recupera el 50% -> ENTRAR LARGO (1 vez).
  - Salir:  WIN si el RSI llega a sobrecompra (>=70) antes de volver a <=30.
            LOSS si el RSI vuelve a sobreventa (<=30) antes de llegar a 70.
  - Mide el movimiento de PRECIO real (entry/exit al close 1H).

Compara K = 1..4 para ver donde estan las mejores probabilidades.
"""
import csv
import rsi_1h_signal as r1

CSV_1H = (r"C:\Users\leyner\Documents\proyectos\trading\binance"
          r"\historical_data\klines_1h\BNBUSDT_1h_20240101_20260615.csv")
LO, MID, HI = 30, 50, 70


def cargar():
    cl = []
    with open(CSV_1H, newline="") as f:
        rd = csv.reader(f)
        next(rd)
        for row in rd:
            cl.append(float(row[4]))
    return cl, r1.rsi_wilder(cl, 14)


def backtest(rsi, closes, K):
    trades = []                 # ret% de cada operacion (signed)
    estado, cuenta = "MID", 0
    pos_entry = None
    ya_entro = False
    for i, x in enumerate(rsi):
        if x is None:
            continue
        if pos_entry is not None:                 # operacion abierta
            if x >= HI:
                trades.append((closes[i] / closes[pos_entry] - 1) * 100)
                pos_entry = None
                estado, cuenta, ya_entro = "ALTO", 0, False
            elif x <= LO:
                trades.append((closes[i] / closes[pos_entry] - 1) * 100)
                pos_entry = None
                cuenta += 1                        # esta caida es otra visita
                estado = "BAJO"
            continue
        if estado == "MID":
            if x >= HI:
                cuenta, estado, ya_entro = 0, "ALTO", False
            elif x <= LO:
                cuenta += 1
                estado = "BAJO"
        elif estado == "BAJO":
            if x >= HI:
                cuenta, estado, ya_entro = 0, "ALTO", False
            elif x >= MID:
                estado = "MID"
                if cuenta >= K and not ya_entro:   # ENTRADA
                    pos_entry = i
                    ya_entro = True
        elif estado == "ALTO":
            if x <= LO:
                cuenta, estado = 1, "BAJO"
            elif x <= MID:
                estado = "MID"
    return trades


def stats(trades):
    n = len(trades)
    if n == 0:
        return None
    wins = [r for r in trades if r > 0]
    losses = [r for r in trades if r <= 0]
    wr = len(wins) / n * 100
    aw = sum(wins) / len(wins) if wins else 0
    al = sum(losses) / len(losses) if losses else 0
    exp = sum(trades) / n
    return n, wr, aw, al, exp, min(trades), max(trades)


def main():
    closes, rsi = cargar()
    print("Senal 'K visitas a sobreventa -> largo'  |  BNBUSDT 1H 2024-2026")
    print("Exit: WIN si RSI>=70, LOSS si RSI vuelve a <=30 (precio al close)")
    print("=" * 74)
    print(f"  {'K':>2} {'trades':>6} {'win%':>6} {'avgWin':>8} {'avgLoss':>8} "
          f"{'exp/trade':>9} {'peorLoss':>9}")
    print("  " + "-" * 64)
    for K in [1, 2, 3, 4]:
        s = stats(backtest(rsi, closes, K))
        if not s:
            continue
        n, wr, aw, al, exp, mn, mx = s
        print(f"  {K:>2} {n:>6} {wr:>5.0f}% {aw:>+7.2f}% {al:>+7.2f}% "
              f"{exp:>+8.2f}% {mn:>+8.2f}%")
    print("  " + "-" * 64)
    print("  exp/trade = ganancia media por operacion en % de precio (sin apalancar)")


if __name__ == "__main__":
    main()
