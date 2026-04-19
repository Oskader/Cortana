# Cortana 2026 — Institutional Trading Bot

Cortana es un sistema de trading algorítmico institucional diseñado para operar Swing Trading en renta variable estadounidense con capitales desde **$10 USD**. Emplea metodologías ICT / Smart Money Concepts (SMC) combinadas con Inteligencia Artificial Reflexiva a través de la API de Groq, implementando Fractional Shares de forma automática en Alpaca API.

## Funcionalidad & Características Clave
- **Virtual Brackets**: Como Alpaca no soporta el OCO Server-Side para compras fraccionarias de acciones (necesarias para una cuenta de bajo capital), el bot asume el rol del Broker. Manda órdenes "Notional" de Fractional Share e instruye la ejecución de Stop Losses y Take Profits asincrónicamente mediante *WebSockets* contra los precios de los ticks en vivo.
- **Smart Money Concepts (SMC)**: Implementación de *Fair Value Gaps* (OB y FVG) que combinan la confluencia de análisis técnicos macro junto a un score AI para detectar liquidez y cazadores de stops.
- **Riesgo por Kelly Criterion**: Se ajusta matemáticamente sin intervención humana, reduciendo exposición en base a la performance de la bitácora SQlite.
- **Circuit Breakers Intocables**: Halt si hay drawdowns de `-25%`, Pausas en `-15%`.
- **PDT Compliance Activo**: Registra transacciones en vivo, contando `Round-trips` durante los últimos **5 business days** para no superar las restricciones impuestas por la SEC en cuentas menores a $25,000 USD. 
- **Conciencia del Mercado**: Detecta regímenes Macro y alta volatilidad por la ecuación VIX>25, rechazando operaciones y achicando posiciones automáticamente.

## Requisitos y Configuración
Necesitas Python 3.10 o posterior instalado.

1. **Instalar Dependencias** (Las versiones incluidas incluyen `portalocker` para prevenir condiciones de carrera).
```bash
pip install -r requirements.txt
```

2. **Configuración del Entorno**
Copia el archivo enviroment proveído y reellénalo:
```bash
cp .env.example .env
```
Añade tus tokens API de Alpaca, Groq `llama-3.3-70b-versatile`, Telegram Chat ID, y NewsAPI. Modifica si tu cuenta está en "live" o "paper".

## Uso y Lanzamiento
Iniciar la instancia es muy simple. Entra a la carpeta de tu repositorio y ejecuta:

```bash
python main.py
```

En Telegram, el Bot responderá si estabas incluído en la array del Chat ID. Usa `/start` para recibir confirmación de diagnósticos o `/status` para entender si la posición VIX está suspendiendo aperturas de tu bot.

## Plan Escalable
Consulta el archivo `growth_plan.md` si cuentas con planes para escalar el capital a más de $25,000 USD.

## Disclaimer Risk
El software de ejecución ejecuta Fractional Buying y no tiene afiliación con los brokers. Revisa siempre el funcionamiento en modo "paper" operando hasta asegurar la rentabilidad.
