CHALLENGE_REF := 5bee8420d85cb5737b2d2e1648b20c682b713a9b
CHALLENGE_URL := https://raw.githubusercontent.com/codecon-dev/versus-rinha-de-backend/$(CHALLENGE_REF)/editions/02-pix
CORRECTNESS_FILES := package.json package-lock.json vitest.config.ts helpers.ts \
	round1-basics.test.ts round2-funds.test.ts \
	round3-idempotency.test.ts round4-concurrency.test.ts
LOAD_FILES := throughput.js latency.js
API_URL ?= http://localhost:3000
DOCKER ?= docker
STATS_FILE := /tmp/vessel-stats.txt

.PHONY: help lint lint-fix format format-check check test challenge verify bench wait stats stats-peak

help:
	@echo "Available commands in Makefile:"
	@echo "  make help         - Show this help message"
	@echo "  make lint         - Run linter (ruff check)"
	@echo "  make lint-fix     - Automatically fix linter issues (ruff check --fix)"
	@echo "  make format       - Format code (ruff format)"
	@echo "  make format-check - Check code formatting (ruff format --check)"
	@echo "  make check        - Run linter and check formatting"
	@echo "  make test         - Run tests (pytest tests/ -v)"
	@echo "  make challenge    - Download challenge test suites and install dependencies"
	@echo "  make verify       - Run correctness tests (vitest)"
	@echo "  make bench        - Run load tests (k6)"
	@echo "  make wait         - Wait for API to be healthy"
	@echo "  make stats        - Record docker stats to file"
	@echo "  make stats-peak   - Show top 5 peak stats"

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check --fix .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

check: lint format-check

test:
	uv run pytest tests/ -v

challenge:
	@mkdir -p challenge/correctness challenge/load
	@for f in $(CORRECTNESS_FILES); do \
		curl -sfS -o challenge/correctness/$$f \
			$(CHALLENGE_URL)/tests/correctness/$$f || exit 1; \
	done
	@for f in $(LOAD_FILES); do \
		curl -sfS -o challenge/load/$$f $(CHALLENGE_URL)/tests/load/$$f || exit 1; \
	done
	@cd challenge/correctness && npm install

wait:
	@printf 'waiting for %s/health' $(API_URL)
	@until curl -sf $(API_URL)/health > /dev/null 2>&1; do \
		printf '.'; sleep 0.2; \
	done
	@echo ' ok'

verify: wait
	@cd challenge/correctness && API_URL=$(API_URL) npx vitest run --reporter=verbose

bench: wait
	@cd challenge/load && k6 run throughput.js && k6 run latency.js

stats:
	@: > $(STATS_FILE)
	@echo "recording to $(STATS_FILE) — ctrl-c to stop"
	@while true; do \
		$(DOCKER) stats --no-stream \
			--format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' >> $(STATS_FILE); \
		sleep 1; \
	done

stats-peak:
	@sort -t' ' -k2 -gr $(STATS_FILE) | head -5

