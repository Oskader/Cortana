.PHONY: help run-paper run-live test lint logs stop report backup-db install clean

help: ## Mostrar este menú de ayuda
	@echo "═══════════════════════════════════════"
	@echo "  CORTANA BOT — Comandos disponibles"
	@echo "═══════════════════════════════════════"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Instalar dependencias
	pip install -r requirements.txt

run-paper: ## Iniciar bot en modo PAPER (simulación)
	TRADING_MODE=paper python main.py

run-live: ## Iniciar bot en modo LIVE (dinero real — CUIDADO)
	@echo "⚠️  MODO LIVE — ¿Estás seguro? (Ctrl+C para cancelar)"
	@sleep 3
	TRADING_MODE=live python main.py

test: ## Ejecutar todos los tests
	python -m pytest tests/ -v --asyncio-mode=auto

lint: ## Verificar calidad de código
	python -m py_compile main.py
	python -c "from trading_bot.config.settings import settings; print('✅ Settings OK')"

logs: ## Ver logs en tiempo real
	tail -f logs/bot.log

stop: ## Detener el bot (Docker)
	docker-compose down

report: ## Ver reporte del día actual
	python -c "from trading_bot.utils.db import TradeJournal; j=TradeJournal(); print(j.get_daily_summary())"

backup-db: ## Backup del SQLite con timestamp
	cp data/trading_bot.db "data/backup_$$(date +%Y%m%d_%H%M%S).db"

docker-build: ## Construir imagen Docker
	docker-compose build

docker-up: ## Iniciar con Docker Compose
	docker-compose up -d

docker-logs: ## Ver logs del contenedor
	docker-compose logs -f

clean: ## Limpiar archivos temporales
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache
