"""
Exploracion del PATRON del RSI 1H (BNBUSDT), sobre historia local 2024-2026.

Hipotesis: el precio cae a SOBREVENTA (<=30), sube a su mitad (50), oscila
ahi acumulando, y vuelve a caer a sobreventa. Cada caida es una "visita".
Tras varias visitas, finalmente rompe a SOBRECOMPRA (>=70).

Mide:
  1) Cuantas visitas a sobreventa hay antes de cada ruptura a sobrecompra.
  2) HAZARD: P(romper a sobrecompra justo despues de la visita K | llegaste a K).
     -> si sube con K, despues de K visitas conviene apostar al rompimiento.
  3) Lo mismo en espejo para sobrecompra -> sobreventa.
"""
import csv
from collections import Counter

import rsi_1h_signal as r1

CSV_1H = (r"C:\Users\leyner\Documents\proyectos\trading\binance"
          r"\historical_data\klines_1h\BNBUSDT_1h_20240101_20260615.csv")
OVERSOLD, MID, OVERBOUGHT = 30, 50, 70


def cargar_rsi():
    cl = []
    with open(CSV_1H, newline="") as f:
        rd = csv.reader(f)
        next(rd)
        for row in rd:
            cl.append(float(row[4]))
    return r1.rsi_wilder(cl, 14)


def visitas_antes_de_ruptura(rsi, lo, mid, hi):
    """Cuenta visitas a la zona BAJA (<=lo) antes de cada ruptura a la zona
    ALTA (>=hi). Una nueva visita solo cuenta si el RSI se recupero por
    encima de 'mid' desde la ultima visita. Devuelve lista de conteos."""
    seqs = []
    estado = "MID"          # MID | BAJO | ALTO
    cuenta = 0
    for x in rsi:
        if x is None:
            continue
        if estado == "MID":
            if x >= hi:
                seqs.append(cuenta)
                cuenta = 0
                estado = "ALTO"
            elif x <= lo:
                cuenta += 1
                estado = "BAJO"
        elif estado == "BAJO":          # en zona baja, espera recuperar mid
            if x >= hi:                  # salto directo a ruptura
                seqs.append(cuenta)
                cuenta = 0
                estado = "ALTO"
            elif x >= mid:
                estado = "MID"
        elif estado == "ALTO":          # tras ruptura, espera volver bajo mid
            if x <= lo:                  # salto directo a la zona baja
                cuenta = 1
                estado = "BAJO"
            elif x <= mid:
                estado = "MID"
    return seqs


def reporte(nombre, seqs, kmax=8):
    n = len(seqs)
    print("=" * 60)
    print(f"  {nombre}  ->  {n} secuencias completas (terminan en ruptura)")
    print("=" * 60)
    if n == 0:
        return
    dist = Counter(seqs)
    print("  Visitas antes de la ruptura:")
    for k in range(0, max(dist) + 1):
        c = dist.get(k, 0)
        if c:
            barra = "#" * round(c / n * 40)
            print(f"    {k:>2} visitas: {c:>3}  ({c/n*100:>4.0f}%) {barra}")
    prom = sum(seqs) / n
    print(f"  Promedio de visitas por secuencia: {prom:.2f}")
    print("-" * 60)
    print("  HAZARD  P(romper justo despues de la visita K | llegaste a K):")
    print(f"  {'K':>3} {'llegaron':>9} {'rompieron':>9} {'P(romper)':>10} {'siguen':>8}")
    for k in range(1, kmax + 1):
        llego = sum(1 for c in seqs if c >= k)
        rompio = sum(1 for c in seqs if c == k)
        if llego == 0:
            continue
        p = rompio / llego * 100
        print(f"  {k:>3} {llego:>9} {rompio:>9} {p:>9.0f}% {llego - rompio:>8}")


def main():
    rsi = cargar_rsi()
    validos = sum(1 for x in rsi if x is not None)
    print(f"Velas 1H con RSI: {validos}  (sobreventa<= {OVERSOLD}, mid {MID}, "
          f"sobrecompra>= {OVERBOUGHT})\n")
    # Sobreventa -> sobrecompra
    seq_os = visitas_antes_de_ruptura(rsi, OVERSOLD, MID, OVERBOUGHT)
    reporte("SOBREVENTA -> SOBRECOMPRA (visitas a sobreventa)", seq_os)
    print()
    # Espejo: sobrecompra -> sobreventa  (invertimos: zona baja=sobrecompra)
    seq_ob = visitas_antes_de_ruptura(
        [(100 - x if x is not None else None) for x in rsi],
        100 - OVERBOUGHT, 100 - MID, 100 - OVERSOLD)
    reporte("SOBRECOMPRA -> SOBREVENTA (visitas a sobrecompra)", seq_ob)


if __name__ == "__main__":
    main()
