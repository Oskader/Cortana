import json
import asyncio
from typing import Dict, Any, Optional
from groq import Groq
from loguru import logger
from ..config.settings import settings

SYSTEM_PROMPT = """
Eres un quant trader algorítmico experto con 15 años de experiencia en mercados de renta variable estadounidenses. 
Tu objetivo es analizar el contexto del mercado y tomar decisiones de trading precisas.

REGLAS DE OPERATORIA:
- Confluencia: Busca alineación entre indicadores técnicos, noticias y contexto macro.
- Riesgo: Nunca recomendar >5% del portfolio en una sola posición.
- Tiempo: No operar en los primeros/últimos 5 minutos del mercado.
- Formato: SIEMPRE responder en JSON estricto.

ESQUEMA DE RESPUESTA OBLIGATORIO:
{
  "action": "BUY" | "SELL" | "HOLD" | "CLOSE",
  "ticker": "TICKER",
  "confidence": 0.0-1.0,
  "reasoning": "Resumen de confluencia en 3 oraciones",
  "entry_price_target": 0.0,
  "stop_loss": 0.0,
  "take_profit": 0.0,
  "time_horizon": "intraday" | "swing" | "position",
  "risk_reward_ratio": 0.0,
  "invalidation_condition": "Condición técnica de invalidación"
}
"""

class GroqAgent:
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.history = []

    async def chat(self, prompt: str, system_override: Optional[str] = None) -> Dict[str, Any]:
        """Realiza una llamada simple a Groq"""
        try:
            response = self.client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_override or SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"Error en llamada a Groq: {e}")
            return {"action": "HOLD", "confidence": 0, "reasoning": f"Error API: {str(e)}"}

    async def analyze_with_reflection(self, context: str) -> Dict[str, Any]:
        """
        Implementa el Reflection Pattern en 3 pasos:
        1. Análisis inicial
        2. Abogado del diablo
        3. Síntesis final
        """
        logger.info("Iniciando análisis con Reflection Pattern...")

        # Paso 1: Análisis Técnico e Inicial
        step1 = await self.chat(f"Analiza este contexto y genera una señal inicial: {context}")
        
        if step1.get("action") == "HOLD":
            return step1

        # Paso 2: Devil's Advocate
        devil_prompt = f"""
        Actúa como un gestor de riesgos senior (Devil's Advocate). 
        Se ha propuesto la siguiente operación: {json.dumps(step1)}
        Basado en el contexto: {context}
        
        ¿Por qué esta señal podría ser falsa o peligrosa? Identifica al menos 3 riesgos críticos.
        Responde en JSON con la clave 'critique'.
        """
        step2 = await self.chat(devil_prompt, system_override="Eres un analista de riesgos pesimista y meticuloso.")
        
        # Paso 3: Síntesis Final
        final_prompt = f"""
        Contexto original: {context}
        Señal inicial: {json.dumps(step1)}
        Crítica de riesgo: {json.dumps(step2)}
        
        Realiza una síntesis final. Si los riesgos son críticos e invalidan el setup, cambia a HOLD.
        Si la señal sobrevive a la crítica, ajusta el confidence y los niveles si es necesario.
        Responde con el esquema obligatorio original.
        """
        final_decision = await self.chat(final_prompt)
        
        logger.info(f"Decisión final: {final_decision.get('action')} (Confidence: {final_decision.get('confidence')})")
        return final_decision
