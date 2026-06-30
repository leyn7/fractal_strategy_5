"""
Conteo de FASES sobre temporalidad 3m, ancladas en el minimo de la
penultima sobreventa (RSI 1H).

Mecanica (fibo de seguimiento, solo nivel 50%):
  - Ancla 0% = MIN_PRICE (fijo). Techo 100% = max high alcanzado (trailing).
  - 50% = (ancla + techo) / 2.
  - FASE: tras hacer techo, el precio baja y su low toca el 50%.
  - Fase >=2: requiere romper el techo anterior (nuevo high) SIN superar
    techo_prev + 1.5*(techo_prev - ancla)  (= "150%" trailing).
  - Ruptura: si un techo nuevo supera ese 150% -> se detiene el conteo.
  - Invalidacion: si el low rompe por debajo del ancla -> se detiene.
"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta

SYMBOL = "BNBUSDT"
INTERVAL = "3m"
ANCHOR = 540.50              # minimo de la penultima sobreventa
START_UTC = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)  # margen antes del low
FACTOR_150 = 1.5            # tope: techo_prev + FACTOR_150*(techo_prev - ancla)
BOGOTA = timezone(timedelta(hours=-5))


def fetch_3m(start_dt):
    start_ms = int(start_dt.timestamp() * 1000)
    out = []
    while True:
        url = (
            f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL}"
            f"&interval={INTERVAL}&startTime={start_ms}&limit=1500"
        )
        with urllib.request.urlopen(url, timeout=20) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1500:
            break
        start_ms = batch[-1][0] + 1
    return out


def fmt(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, BOGOTA).strftime("%m-%d %H:%M")


def main():
    kl = fetch_3m(START_UTC)
    kl = kl[:-1]  # quitar vela en formacion
    ot = [k[0] for k in kl]
    hi = [float(k[2]) for k in kl]
    lo = [float(k[3]) for k in kl]

    # Ubicar la vela de 3m con el minimo == ANCHOR (el low real del tramo)
    min_lo = min(lo)
    anchor_idx = lo.index(min_lo)
    print(f"Datos 3m descargados: {len(kl)} velas")
    print(f"Min low del set: {min_lo:.2f} en {fmt(ot[anchor_idx])} (ancla usada: {ANCHOR})")
    start = anchor_idx + 1  # empezamos en la vela SIGUIENTE al minimo
    print(f"Inicio del analisis: {fmt(ot[start])}")
    print("=" * 64)

    anchor = ANCHOR
    running_max = anchor
    prev_techo = anchor
    armed = True            # se puede completar fase (phase1 arrancada)
    phase_count = 0
    fases = []              # (idx_toque, techo, level50, idx_techo_aprox)
    status = "EN CURSO (hasta la ultima vela)"
    techo_time_idx = anchor_idx

    for i in range(start, len(kl)):
        h, l = hi[i], lo[i]

        # invalidacion: rompe el ancla
        if l < anchor:
            status = f"INVALIDADO: el precio rompio {anchor} en {fmt(ot[i])} (low={l:.2f})"
            break

        new_high = h > running_max
        if new_high:
            running_max = h
            techo_time_idx = i

        # ruptura 150% (solo aplica tras la 1a fase)
        if phase_count >= 1:
            cap = prev_techo + FACTOR_150 * (prev_techo - anchor)
            if running_max > cap:
                status = (f"RUPTURA: techo {running_max:.2f} supero el 150% "
                          f"({cap:.2f}) en {fmt(ot[i])}")
                break

        if not armed and running_max > prev_techo:
            armed = True

        level50 = (anchor + running_max) / 2.0

        # fase: precio (low) regresa al 50%, con techo ya formado antes
        if armed and not new_high and running_max > prev_techo and l <= level50:
            phase_count += 1
            fases.append((i, running_max, level50, techo_time_idx))
            prev_techo = running_max
            armed = False

    # Reporte
    print(f"{'#':>2}  {'techo (100%)':>14}  {'cuando techo':>13}   "
          f"{'50% tocado':>11}  {'cuando 50%':>13}")
    print("-" * 64)
    for n, (i, techo, lvl, ti) in enumerate(fases, 1):
        print(f"{n:>2}  {techo:>14.2f}  {fmt(ot[ti]):>13}   "
              f"{lvl:>11.2f}  {fmt(ot[i]):>13}")
    print("=" * 64)
    print(f">> FASES COMPLETADAS: {phase_count}")
    print(f"   Estado: {status}")
    if fases:
        ult_techo = fases[-1][1]
        cap = ult_techo + FACTOR_150 * (ult_techo - anchor)
        nivel50_actual = (anchor + running_max) / 2.0
        print(f"   Ultimo techo: {ult_techo:.2f} | tope 150% siguiente: {cap:.2f}")
        print(f"   Techo (max actual): {running_max:.2f} | 50% actual: {nivel50_actual:.2f}")


if __name__ == "__main__":
    main()
