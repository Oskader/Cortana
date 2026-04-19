# Cortana: Institutional Growth Plan & Scaling Roadmap

Este documento detalla cómo escalar a Cortana de manera profesional y probabilística. El bot fue diseñado para ser riguroso y respetar reglas institucionales (como Fractional Limits y PDT rules) para que los mismos fundamentos matemáticos apliquen desde $10 USD hasta $100,000 USD.

## Stage 1: The Micro-Account Phase ($10 a $100 USD)
*Cortana actualmente opera en esta etapa, sobreviviendo entornos hostiles con baja capitalización.*

- **Estrategia (Actual)**: Uso exclusivo de *Fractional Shares* (`notional`).
- **Problema de Alpaca API**: Bracket orders (Stop Loss y Take Profit en el host de Alpaca) NO admiten shares fraccionados.
- **La Solución**: Cortana emplea **Brackets Virtuales** internos asíncronos (`_on_realtime_bar`), saliendo y deshaciéndose con órdenes de mercado cuando el precio toca umbrales guardados persistentemente en la base de datos (SQLite).
- **Riesgo por trade**: Max ~20%, restringido por la volatilidad medida mediante Kelly Criterion para que Cortana no sea aniquilada en una racha de operaciones perdedoras o gap downs.

## Stage 2: The Acceleration Phase ($100 a $1,000 USD)
*Con más capital, podemos ampliar la diversificación.*

- **Acción a tomar en `.env`**: 
  - Reducir el `MAX_POSITION_SIZE_PCT` del agresivo `0.20` a un más sano `0.05` a `0.10`.
  - Aumentar el `MAX_OPEN_POSITIONS` a 5.
- **Alpaca API**: Cortana continuará operando en Fractional Shares, pero gracias a tener posiciones de >$5 USD por activo sistemáticamente, su deslizamiento en ejecución (slippage fees) será porcentualmente nulo.

## Stage 3: The Institutional Bracket Phase ($1,000 a $25,000 USD)
*Cuando cada trade supera el valor íntegro de 1 share y el buffer no es problema.*

- **Acción en el Código**: En esta etapa, te recomiendo que hagas revert del `submit_notional_order` dentro de `alpaca_client.py` a `submit_bracket_order`, quitando fractional shares y pasando por OCO requests nativas de Alpaca con `qty` de enteros.
- **Ventaja**: Alpaca es un host más rápido para las salidas. Si la VDS fallase u ocurriese un problema de red, el broker tiene las órdenes de SL y TP ancladas.
- **Circuit Breaker Activo**: Permanecerá el bloqueo a 3 day-trades máximo cada 5 días para evitar flaggear la cuenta con estatus Pattern Day Trader (que resultaría en clausura de margin account).

## Stage 4: Unrestricted Scalping ($25,000+ USD)
*Exenta la restricción del PDT, la estrategia se diversifica.*

- **Acción a tomar en `.env`**:
  - Incrementar el límite de trades `MAX_DAILY_TRADES` a `100` o más.
- **Riesgo**: Disminuir el `DRAWDOWN_PAUSE_PCT` a `-0.05` (5%) para parar temprano sin arrastrar capital corporativo, operando SMC en timeframes más cortos (1m o 5m).

Cortana está lista para este viaje. Sus bases de código en `portfolio_sizer.py` la mantendrán siempre controlando el riesgo, creciendo con interés compuesto matemáticamente inquebrantable asumiendo Kelly fractional.
