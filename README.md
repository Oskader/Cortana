# Cortana Trading Bot 🤖

Bot de trading algorítmico institutional-grade para acciones estadounidenses.

**Stack**: Python 3.12 + Alpaca Markets + Groq AI + Telegram

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                     CORTANA ENGINE                          │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌─────────┐  │
│  │ Screener │  │ Data Feed│  │  Indicators │  │  Cache   │  │
│  │ (yfinance│  │ (WebSock)│  │ (pandas-ta) │  │  (TTL)   │  │
│  └────┬─────┘  └────┬─────┘  └──────┬─────┘  └────┬────┘  │
│       │              │               │              │       │
│       └──────────────┼───────────────┼──────────────┘       │
│                      │               │                      │
│               ┌──────▼───────────────▼──────┐               │
│               │      SIGNAL SCORER          │               │
│               │   (0-100 confluencia)       │               │
│               └──────────────┬──────────────┘               │
│                              │ score >= 70                  │
│               ┌──────────────▼──────────────┐               │
│               │       GROQ AI BRAIN         │               │
│               │  ┌─────┐ ┌──────┐ ┌──────┐ │               │
│               │  │Step1│→│Step2 │→│Step3 │ │               │
│               │  │Analy│ │Devil │ │Synth │ │               │
│               │  └─────┘ └──────┘ └──────┘ │               │
│               └──────────────┬──────────────┘               │
│                              │ GroqTradeSignal              │
│               ┌──────────────▼──────────────┐               │
│               │     RISK MANAGER            │               │
│               │  9-point pre-trade check    │               │
│               │  Circuit breakers (hard)    │               │
│               └──────────────┬──────────────┘               │
│                              │ validated                    │
│               ┌──────────────▼──────────────┐               │
│               │   ALPACA BRACKET ORDER      │               │
│               │   Entry + SL + TP (atomic)  │               │
│               └──────────────┬──────────────┘               │
│                              │                              │
│               ┌──────────────▼──────────────┐               │
│               │    TRADE JOURNAL (SQLite)   │               │
│               │    + TELEGRAM NOTIFICATION  │               │
│               └─────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

---

## Requisitos del Sistema

- **Python** 3.12+
- **Cuenta Alpaca Markets** (paper o live) — [alpaca.markets](https://alpaca.markets)
- **API Key de Groq** — [console.groq.com](https://console.groq.com)
- **Bot de Telegram** — [BotFather](https://t.me/BotFather)
- **API Key de NewsAPI** (opcional) — [newsapi.org](https://newsapi.org)

---

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/cortana-bot.git
cd cortana-bot
```

### 2. Crear entorno virtual

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus API keys
```

### 5. Ejecutar

```bash
python main.py
```

---

## Configuración

### Alpaca Markets

1. Crear cuenta en [alpaca.markets](https://alpaca.markets)
2. Ir a Account → API Keys
3. Generar un par de claves (key + secret)
4. Agregar a `.env`:
   ```
   ALPACA_API_KEY=tu_api_key
   ALPACA_SECRET_KEY=tu_secret_key
   ```
5. Para paper trading: `ALPACA_BASE_URL=https://paper-api.alpaca.markets`

### Groq AI

1. Crear cuenta en [console.groq.com](https://console.groq.com)
2. Ir a API Keys → Create
3. Agregar a `.env`:
   ```
   GROQ_API_KEY=gsk_tu_api_key
   ```
4. Modelo recomendado: `llama-3.3-70b-versatile`

### Telegram

1. Hablar con [@BotFather](https://t.me/BotFather) en Telegram
2. Enviar `/newbot` y seguir instrucciones
3. Copiar el token del bot
4. Obtener tu Chat ID con [@userinfobot](https://t.me/userinfobot)
5. Agregar a `.env`:
   ```
   TELEGRAM_TOKEN=tu_token
   TELEGRAM_CHAT_ID=tu_chat_id
   ```

---

## Comandos de Telegram

| Comando | Descripción |
|---------|-------------|
| `/start` | Mensaje de bienvenida |
| `/status` | Estado del bot, equity, P&L, régimen |
| `/portfolio` | Posiciones abiertas con P&L |
| `/report` | Reporte diario de performance |
| `/trades` | Últimos trades realizados |
| `/risk` | Métricas: Sharpe, profit factor, drawdown |
| `/pause` | Pausar trading (no cierra posiciones) |
| `/resume` | Reanudar trading |
| `/help` | Lista de comandos |

---

## Alertas y Reportes

### Alerta de Trade
Cuando se ejecuta un trade, recibes:
- Ticker, cantidad, precio de entrada
- Stop loss y take profit
- Risk/reward ratio
- Confidence del AI
- Razonamiento del análisis

### Reporte Diario
Se envía automáticamente a las **4:05 PM ET** con:
- Trades del día (wins/losses)
- P&L total del día
- Mejor y peor trade
- Métricas acumuladas (Sharpe, PF, WR, DD)

---

## Estructura del Proyecto

```
cortana-bot/
├── main.py                          # Entry point
├── requirements.txt                 # Dependencies
├── .env.example                     # Environment template
├── Dockerfile                       # Docker build
├── docker-compose.yml               # Docker Compose
├── Makefile                         # Automation commands
├── railway.json                     # Railway config
│
├── trading_bot/
│   ├── config/
│   │   ├── constants.py             # All magic numbers
│   │   ├── exceptions.py            # Custom exceptions
│   │   ├── settings.py              # Pydantic Settings
│   │   └── logging_config.py        # Loguru setup
│   │
│   ├── core/
│   │   ├── engine.py                # Main orchestrator
│   │   └── state.py                 # Global state (thread-safe)
│   │
│   ├── brain/
│   │   └── groq_agent.py            # Groq AI + Reflection Pattern
│   │
│   ├── execution/
│   │   └── alpaca_client.py         # Alpaca API wrapper
│   │
│   ├── market/
│   │   ├── cache.py                 # TTL cache
│   │   ├── data_feed.py             # WebSocket stream
│   │   ├── indicators.py            # Technical analysis
│   │   └── screener.py              # Market regime + scanner
│   │
│   ├── risk/
│   │   ├── risk_manager.py          # 9-point pre-trade checklist
│   │   └── portfolio_sizer.py       # Half-Kelly position sizing
│   │
│   ├── telegram/
│   │   └── bot.py                   # Telegram interface
│   │
│   └── utils/
│       └── db.py                    # SQLite trade journal
│
└── tests/
    ├── conftest.py                  # Fixtures & mocks
    ├── test_risk_manager.py
    ├── test_groq_agent.py
    ├── test_signal_scorer.py
    ├── test_order_manager.py
    └── test_full_trade_flow.py
```

---

## Deploy en Railway

1. Conectar el repositorio de GitHub
2. Configurar variables de entorno en Railway Dashboard
3. El bot se deploya automáticamente con cada push

```bash
# O deploy manual con Railway CLI:
railway login
railway link
railway up
```

---

## Troubleshooting

| Problema | Solución |
|----------|----------|
| `ModuleNotFoundError` | Verificar que `pip install -r requirements.txt` se ejecutó |
| `Alpaca API error 403` | Verificar API keys y que la cuenta esté activa |
| `Groq timeout` | Aumentar `GROQ_TIMEOUT` en `.env` |
| `Telegram not responding` | Verificar `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` |
| `SQLite locked` | Solo una instancia del bot debe correr a la vez |
| `No trades executing` | Verificar horario de mercado (9:35-15:50 ET) |
| `Daily loss limit hit` | El bot se auto-pausa. Reiniciar al día siguiente |

---

## FAQ

**¿Puedo usar el bot con dinero real?**
Sí, cambiando `TRADING_MODE=live` y `ALPACA_BASE_URL=https://api.alpaca.markets`. Pero se recomienda al menos 1 mes en paper mode.

**¿Cuánto capital necesito?**
Mínimo recomendado: $2,000 USD para que el position sizing funcione correctamente.

**¿El bot opera en pre/post market?**
No. Solo opera dentro del horario configurado (default: 9:35 AM - 3:50 PM ET).

**¿Puedo agregar más acciones a la watchlist?**
Sí, modificar `WATCHLIST_SYMBOLS` en `.env`. Se recomienda máximo 20-30 para no sobrecargar la API.

**¿Cuántas llamadas a Groq usa por día?**
Aproximadamente 3 llamadas (reflection pattern) × oportunidades detectadas. Con 10 acciones, típicamente 10-30 llamadas/día.
