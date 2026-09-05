.PHONY: help lint lint-fix format format-check check

help:
	@echo "Comandos disponíveis no Makefile:"
	@echo "  make lint         - Executa o linter (ruff check)"
	@echo "  make lint-fix     - Corrige automaticamente problemas do linter (ruff check --fix)"
	@echo "  make format       - Formata o código (ruff format)"
	@echo "  make format-check - Verifica se o código está formatado (ruff format --check)"
	@echo "  make check        - Executa o linter e valida a formatação"

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check --fix .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

check: lint format-check

