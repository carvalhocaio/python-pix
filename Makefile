CHALLENGE_REF := 5bee8420d85cb5737b2d2e1648b20c682b713a9b
CHALLENGE_URL := https://raw.githubusercontent.com/codecon-dev/versus-rinha-de-backend/$(CHALLENGE_REF)/editions/02-pix
CORRECTNESS_FILES := package.json package-lock.json vitest.config.ts helpers.ts \
	round1-basics.test.ts round2-funds.test.ts \
	round3-idempotency.test.ts round4-concurrency.test.ts
LOAD_FILES := throughput.js latency.js
API_URL ?= http://localhost:3000

.PHONY: challenge verify bench

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

verify:
	@cd challenge/correctness && API_URL=$(API_URL) npx vitest run --reporter=verbose

bench:
	@cd challenge/load && k6 run throughput.js && k6 run latency.js
