"""
Integración con Groq AI para análisis de trading con Reflection Pattern.

Implementa:
    - Validación estricta de respuestas con Pydantic (GroqTradeSignal)
    - Reflection Pattern en 3 pasos (análisis → devil's advocate → síntesis)
    - Context builder completo con datos multi-fuente
    - Retry con backoff exponencial y timeout por llamada
    - Logging de tokens consumidos por sesión
    - News API integration para contexto de noticias
"""

import asyncio
import json
import math
import time
from typing import Any, Dict, List, Literal, Optional

import httpx
from groq import Groq
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import constants as C
from ..config.exceptions import GroqParsingError
from ..config.settings import settings


# ═══════════════════════════════════════════════════════════
# SCHEMA DE RESPUESTA — Pydantic Model
# ═══════════════════════════════════════════════════════════

class GroqTradeSignal(BaseModel):
    """Schema validado para las respuestas de trading de Groq."""

    action: Literal["BUY", "SELL", "HOLD", "CLOSE"]
    ticker: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    signal_score: float = Field(default=0.0, ge=0.0, le=10.0)
    reasoning: str = Field(..., min_length=10)
    entry_price_target: float = Field(default=0.01, gt=0)
    stop_loss: float = Field(default=0.01, gt=0)
    take_profit: float = Field(default=0.01, gt=0)
    time_horizon: Literal["intraday", "swing", "position"] = "intraday"
    risk_reward_ratio: float = Field(default=1.0, ge=0.0)
    invalidation_condition: str = "N/A"

    @field_validator("stop_loss")
    @classmethod
    def validate_stop_loss_for_long(cls, v: float, info: Any) -> float:
        """For BUY signals, stop_loss must be below entry_price."""
        data = info.data
        action = data.get("action")
        entry = data.get("entry_price_target")
        if action == "BUY" and entry is not None and entry > 0 and v >= entry:
            raise ValueError(
                f"Stop loss ({v}) debe ser < entry price ({entry}) para BUY"
            )
        return v


# ═══════════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Eres un quant trader algorítmico institucional con 15 años de experiencia \
en mercados de renta variable estadounidenses (NYSE/NASDAQ). \
Especializaciones: análisis técnico multi-timeframe, price action, gestión de riesgo.

═══ REGLAS INVIOLABLES DE RIESGO ═══
1. NUNCA recomendar más del 5% del portfolio en una sola posición.
2. NUNCA operar durante earnings, FDA decisions, o eventos macro críticos.
3. NUNCA recomendar BUY si el stop loss está POR ENCIMA del entry price.
4. NUNCA recomendar un trade con risk/reward ratio < 1.5.
5. NUNCA dar confidence > 0.85 en condiciones de alta volatilidad (VIX > 25).
6. Si hay DUDA, la respuesta SIEMPRE es HOLD.

═══ CUÁNDO USAR CADA ACCIÓN ═══
- BUY: Confluencia técnica clara (3+ indicadores), volumen confirmando, riesgo favorable.
- SELL: Para cerrar posición larga existente. No usamos short selling.
- HOLD: Señal no clara, divergencia entre indicadores, condiciones desfavorables.
- CLOSE: Posición abierta alcanzó TP/SL o tesis invalidada.

═══ PROCESO DE RAZONAMIENTO ═══
1. Analiza estructura de tendencia (EMAs, SuperTrend)
2. Evalúa momentum (RSI, MACD) buscando divergencias
3. Confirma con volumen (VWAP, volumen relativo)
4. Establece niveles de invalidación
5. Calcula risk/reward exacto

═══ FORMATO DE RESPUESTA ═══
Responde EXCLUSIVAMENTE en JSON válido:
{
  "action": "BUY" | "SELL" | "HOLD" | "CLOSE",
  "ticker": "TICKER",
  "confidence": 0.0-1.0,
  "signal_score": 0.0-10.0,
  "reasoning": "Resumen de confluencia en 3 oraciones. Evalúa el peso de SMC (FVG/OB).",
  "entry_price_target": 0.0,
  "stop_loss": 0.0,
  "take_profit": 0.0,
  "time_horizon": "intraday" | "swing" | "position",
  "risk_reward_ratio": 0.0,
  "invalidation_condition": "Condición que invalida el setup"
}"""

DEVILS_ADVOCATE_PROMPT = (
    "Eres un analista de riesgos senior pesimista y meticuloso con 20 años "
    "de experiencia. Tu trabajo es encontrar fallas en las tesis de trading. "
    "Nunca seas complaciente. Responde siempre en JSON."
)


# ═══════════════════════════════════════════════════════════
# NEWS FETCHER
# ═══════════════════════════════════════════════════════════

async def fetch_news_for_ticker(ticker: str) -> str:
    """
    Fetch latest news headlines for a ticker from NewsAPI.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Formatted string of recent headlines, or message if unavailable.
    """
    if not settings.NEWS_API_KEY:
        return "Noticias no disponibles (NEWS_API_KEY no configurada)"

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": ticker,
        "sortBy": "publishedAt",
        "pageSize": C.NEWS_MAX_ARTICLES,
        "apiKey": settings.NEWS_API_KEY,
        "language": "en",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        articles = data.get("articles", [])
        if not articles:
            return "Sin noticias recientes"

        headlines = []
        for article in articles[:C.NEWS_MAX_ARTICLES]:
            title = article.get("title", "N/A")
            source = article.get("source", {}).get("name", "Unknown")
            headlines.append(f"- [{source}] {title}")

        return "\n".join(headlines)

    except Exception as e:
        logger.warning(f"Error fetching news for {ticker}: {e}")
        return "Error obteniendo noticias"


# ═══════════════════════════════════════════════════════════
# GROQ AGENT
# ═══════════════════════════════════════════════════════════

class GroqAgent:
    """
    Agente de IA para análisis de mercado usando Groq con Reflection Pattern.

    Flow completo:
        1. build_context() → construye el prompt con todos los datos
        2. analyze_with_reflection() → 3 llamadas: análisis → crítica → síntesis
        3. parse_and_validate() → valida JSON con Pydantic GroqTradeSignal
    """

    def __init__(self) -> None:
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self._total_tokens_used: int = 0

    # ═══════════════════════════════════════
    # CORE API CALL
    # ═══════════════════════════════════════

    @retry(
        wait=wait_exponential(min=1, max=10),
        stop=stop_after_attempt(C.GROQ_MAX_RETRIES),
    )
    async def _call_groq(
        self,
        prompt: str,
        system_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Realiza una llamada async a Groq con timeout y retry.

        Args:
            prompt: El prompt del usuario.
            system_override: System prompt alternativo (para devil's advocate).

        Returns:
            Dict parseado del JSON de respuesta.
        """
        start = time.monotonic()
        raw_content = ""

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=settings.GROQ_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": system_override or SYSTEM_PROMPT,
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=C.GROQ_TEMPERATURE,
                ),
                timeout=float(settings.GROQ_TIMEOUT),
            )

            # Log token usage
            if response.usage:
                tokens = response.usage.total_tokens
                self._total_tokens_used += tokens
                elapsed = time.monotonic() - start
                logger.debug(
                    f"Groq: {tokens} tokens, {elapsed:.2f}s "
                    f"(session total: {self._total_tokens_used})"
                )

            raw_content = response.choices[0].message.content
            cleaned_content = self._clean_json_response(raw_content)
            return json.loads(cleaned_content)

        except asyncio.TimeoutError:
            logger.error(f"Groq timeout after {settings.GROQ_TIMEOUT}s")
            return self._fallback_hold("Timeout en llamada a Groq")

        except json.JSONDecodeError as e:
            logger.error(f"Groq returned invalid JSON: {e}")
            raise GroqParsingError(raw_response=raw_content, reason=str(e))

        except GroqParsingError:
            raise

        except Exception as e:
            logger.error(f"Groq API error: {type(e).__name__}: {e}")
            return self._fallback_hold(f"Error API: {str(e)}")

    def _clean_json_response(self, content: str) -> str:
        """
        Clean the raw content from Groq to ensure it's a valid JSON string.
        Handles markdown code blocks (```json ... ```).
        """
        content = content.strip()
        # Remove markdown fences if present
        if content.startswith("```"):
            # Split by lines and remove first and last line if they are fences
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
        
        # In case the AI still included some text before/after the first/last { }
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1:
            content = content[start_idx : end_idx + 1]
            
        return content

    @staticmethod
    def _fallback_hold(reason: str) -> Dict[str, Any]:
        """Generate a safe HOLD response as fallback."""
        return {
            "action": "HOLD",
            "ticker": "N/A",
            "confidence": 0.0,
            "signal_score": 0.0,
            "reasoning": reason,
            "entry_price_target": 0.01,
            "stop_loss": 0.01,
            "take_profit": 0.01,
            "time_horizon": "intraday",
            "risk_reward_ratio": 0.0,
            "invalidation_condition": "Fallback — no trade",
        }

    # ═══════════════════════════════════════
    # VALIDATION
    # ═══════════════════════════════════════

    def parse_and_validate(
        self,
        raw: Dict[str, Any],
    ) -> Optional[GroqTradeSignal]:
        """
        Validate Groq's response against the Pydantic schema.

        Args:
            raw: Dict parsed from the JSON response.

        Returns:
            Validated GroqTradeSignal, or None if validation fails.
        """
        try:
            signal = GroqTradeSignal(**raw)

            # Additional business rule: minimum risk/reward
            if (
                signal.action in ("BUY", "SELL")
                and signal.risk_reward_ratio < C.MIN_RISK_REWARD_RATIO
            ):
                logger.warning(
                    f"Risk/reward {signal.risk_reward_ratio:.2f} < "
                    f"minimum {C.MIN_RISK_REWARD_RATIO}"
                )
                return None

            # New Rule: Check AI scoring limit
            min_score = float(settings.model_dump().get("GROQ_MIN_SCORE", 7.0))
            if signal.action == "BUY" and signal.signal_score < min_score:
                logger.warning(
                    f"Signal score {signal.signal_score:.1f} < "
                    f"minimum {min_score}"
                )
                return None

            return signal

        except Exception as e:
            logger.error(
                f"Groq validation failed: {e} | Raw: {json.dumps(raw, default=str)[:500]}"
            )
            return None

    # ═══════════════════════════════════════
    # CONTEXT BUILDER
    # ═══════════════════════════════════════

    async def build_context(
        self,
        ticker: str,
        score: int,
        indicators: Dict[str, Any],
        account_info: Dict[str, Any],
        market_regime: str,
        recent_trades: List[Dict[str, Any]],
        news: str = "",
    ) -> str:
        """
        Build the complete context string for Groq analysis.

        Args:
            ticker: Stock ticker symbol.
            score: Technical signal score (0-100).
            indicators: Dict with current indicator values from last bar.
            account_info: Dict with equity, buying_power, daily_pnl_pct.
            market_regime: Current market regime string.
            recent_trades: Last N trades for pattern context.
            news: Formatted news headlines string.

        Returns:
            Formatted context string ready for Groq.
        """
        ctx = f"""
═══ ANÁLISIS DE {ticker} ═══

▸ Score Técnico: {score}/100
▸ Régimen de Mercado: {market_regime}

─── PRECIO Y TENDENCIA ───
Precio actual: ${self._fmt(indicators.get('close'))}
EMA 9: {self._fmt(indicators.get('EMA_9'))}
EMA 21: {self._fmt(indicators.get('EMA_21'))}
EMA 50: {self._fmt(indicators.get('EMA_50'))}
EMA 200: {self._fmt(indicators.get('EMA_200'))}
SuperTrend Dir: {indicators.get('SUPERT_DIR', 'N/A')}

─── MOMENTUM ───
RSI (14): {self._fmt(indicators.get('RSI'))}
MACD: {self._fmt(indicators.get('MACD'), 4)}
MACD Signal: {self._fmt(indicators.get('MACD_S'), 4)}
MACD Histogram: {self._fmt(indicators.get('MACD_H'), 4)}

─── VOLATILIDAD ───
ATR (14): {self._fmt(indicators.get('ATR'))}
BB Upper: {self._fmt(indicators.get('BBU'))}
BB Middle: {self._fmt(indicators.get('BBM'))}
BB Lower: {self._fmt(indicators.get('BBL'))}

─── VOLUMEN ───
VWAP: {self._fmt(indicators.get('VWAP'))}
Volumen Relativo: {self._fmt(indicators.get('REL_VOL'))}x

─── CUENTA ───
Equity: ${account_info.get('equity', 0):,.2f}
Buying Power: ${account_info.get('buying_power', 0):,.2f}
P&L del día: {account_info.get('daily_pnl_pct', 0):+.2%}
Posiciones abiertas: {account_info.get('position_count', 0)}

─── NOTICIAS RECIENTES ───
{news if news else 'Sin noticias disponibles'}

─── HISTORIAL RECIENTE DEL BOT ───
{self._format_recent_trades(recent_trades)}
"""
        return ctx.strip()

    @staticmethod
    def _fmt(val: Any, decimals: int = 2) -> str:
        """Format a numeric value safely, handling None and NaN."""
        if val is None:
            return "N/A"
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return "N/A"
            return f"{f:.{decimals}f}"
        except (TypeError, ValueError):
            return str(val)

    @staticmethod
    def _format_recent_trades(trades: List[Dict[str, Any]]) -> str:
        """Format recent trades for Groq context."""
        if not trades:
            return "Sin historial de trades"

        lines = []
        for t in trades[-C.TRADES_HISTORY_LIMIT:]:
            pnl = t.get("pnl_dollar", 0)
            emoji = "✅" if pnl > 0 else "❌"
            lines.append(
                f"{emoji} {t.get('ticker', '?')} | "
                f"{t.get('side', '?')} | "
                f"P&L: ${pnl:+.2f} | "
                f"Reason: {t.get('exit_reason', 'N/A')}"
            )
        return "\n".join(lines)

    # ═══════════════════════════════════════
    # REFLECTION PATTERN
    # ═══════════════════════════════════════

    async def analyze_with_reflection(
        self,
        context: str,
    ) -> Optional[GroqTradeSignal]:
        """
        Complete analysis using the Reflection Pattern (3 Groq calls).

        Steps:
            1. Initial technical analysis → generate signal
            2. Devil's advocate → identify risks and counterarguments
            3. Final synthesis → adjusted decision accounting for risks

        Args:
            context: Complete context string from build_context().

        Returns:
            Validated GroqTradeSignal, or None if analysis fails or decides HOLD.
        """
        logger.info("🧠 Reflection Pattern: Starting (3 steps)...")

        # ─── Step 1: Initial Analysis ───
        step1_raw = await self._call_groq(
            f"Analiza este contexto de mercado y genera una señal:\n\n{context}"
        )
        step1 = self.parse_and_validate(step1_raw)

        if step1 is None or step1.action == "HOLD":
            logger.info("Step 1 → HOLD. Stopping reflection.")
            return step1

        logger.info(
            f"Step 1 → {step1.action} {step1.ticker} "
            f"(conf={step1.confidence:.2f})"
        )

        # ─── Step 2: Devil's Advocate ───
        devil_prompt = (
            f"Se propone esta operación:\n"
            f"{json.dumps(step1_raw, indent=2)}\n\n"
            f"Contexto del mercado:\n{context}\n\n"
            f"Identifica:\n"
            f"1. Al menos 3 razones por las que esta señal podría ser FALSA\n"
            f"2. Escenarios de pérdida máxima realistas\n"
            f"3. Factores que podrían invalidar el setup\n\n"
            f'Responde en JSON: {{"critique": "...", "risk_level": '
            f'"LOW"|"MEDIUM"|"HIGH"|"CRITICAL", "should_proceed": true/false, '
            f'"adjusted_confidence": 0.0-1.0, "adjusted_score": 0.0-10.0}}'
        )

        step2_raw = await self._call_groq(
            devil_prompt, system_override=DEVILS_ADVOCATE_PROMPT,
        )
        logger.info(
            f"Step 2 → Risk={step2_raw.get('risk_level', '?')}, "
            f"Proceed={step2_raw.get('should_proceed', '?')}"
        )

        # ─── Step 3: Final Synthesis ───
        synthesis_prompt = (
            f"Contexto del mercado:\n{context}\n\n"
            f"Señal inicial:\n{json.dumps(step1_raw, indent=2)}\n\n"
            f"Crítica del analista de riesgos:\n{json.dumps(step2_raw, indent=2)}\n\n"
            f"SÍNTESIS FINAL:\n"
            f"- Si riesgos CRÍTICOS invalidan el setup → HOLD\n"
            f"- Si la señal sobrevive → ajusta confidence y niveles\n"
            f"- Confidence final DEBE ser ≤ al inicial si hay riesgos válidos\n"
            f"Responde con el schema de trading obligatorio."
        )

        final_raw = await self._call_groq(synthesis_prompt)
        final_signal = self.parse_and_validate(final_raw)

        if final_signal:
            logger.info(
                f"Step 3 (Final) → {final_signal.action} {final_signal.ticker} "
                f"conf={final_signal.confidence:.2f}, "
                f"RR={final_signal.risk_reward_ratio:.1f}"
            )
        else:
            logger.warning("Step 3 → Validation failed. Result: HOLD")

        return final_signal

    @property
    def total_tokens_used(self) -> int:
        """Total tokens consumed in this session."""
        return self._total_tokens_used
