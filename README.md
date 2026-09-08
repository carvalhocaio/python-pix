# Vessel

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![Checked with pyright](https://img.shields.io/badge/types-pyright-green.svg)](https://github.com/microsoft/pyright)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

High-performance PIX transfer ledger and asynchronous settlement engine built for the **Codecon Rinha de Backend (02 - PIX)** challenge.

Vessel is engineered for ultra-low latency, high throughput, and strict correctness under heavy concurrency, achieving single-digit millisecond response times under high concurrency loads.

---

## Key Architectural Principles

- **Zero-Overhead ASGI Core**: Built directly on top of `uvicorn`, `uvloop`, and `httptools` without heavyweight web frameworks. Routing uses an allocation-free prefix-matched `resolve()` engine.
- **In-Memory Ledger**: Transfers and account states are processed entirely in-memory on the asyncio event loop, eliminating transaction locking bottlenecks and lock contention.
- **Pre-Rendered Wire Encoding**: Transfer payloads are pre-encoded as byte slices using `msgspec` immediately upon settlement. Statement endpoints (`GET /accounts/{id}/statement`) assemble the JSON payload using reverse-ordered byte splicing without re-serializing entries on the fly.
- **Asynchronous Dual-Worker Pipeline**:
  - **Settlement Worker**: Drains and applies pending transfers in configurable micro-batches (`DEFAULT_BATCH_SIZE=512`), validating balances and enforcing FIFO arrival order.
  - **Persistence Worker**: Write-behind worker that drains settled transfers and dirty balances, persisting them to PostgreSQL in bulk via `asyncpg` without blocking request lifecycles.
- **Strict Idempotency**: Guarantees exactly-once settlement per `idempotencyKey` with cached responses for duplicated submissions.

---

## System Overview

```
                      +---------------------------------------+
                      |             HTTP Clients              |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |         Raw ASGI HTTP Router          |
                      |   (uvloop + httptools + msgspec)      |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |            In-Memory Ledger           |
                      |  - Account balances & histories       |
                      |  - Pending transfer FIFO queue        |
                      |  - Idempotency key registry           |
                      +---------------------------------------+
                               /                     \
                              /                       \
                             v                         v
              +----------------------+      +----------------------+
              |  Settlement Worker   |      |  Persistence Worker  |
              |  - Batch settlement  |      |  - Batch balance sync|
              |  - State transitions |      |  - Batch transfer log|
              |  - Pre-render bytes  |      +----------------------+
              +----------------------+                 |
                                                       v
                                            +----------------------+
                                            |  PostgreSQL Storage  |
                                            +----------------------+
```

---

## API Reference

All requests and responses use `application/json`. Timestamps follow ISO 8601 UTC with microsecond precision. Amounts are represented in integer cents (`100 = R$ 1,00`).

### Health Check

```http
GET /health
```

**Response (`200 OK`)**:
```json
{
  "status": "ok"
}
```

---

### Create Account

```http
POST /accounts
```

**Request**:
```json
{
  "id": "acc-payer-1",
  "balance": 100000
}
```

**Responses**:
- `201 Created`: Account successfully registered.
- `409 Conflict`: Account ID already exists.
- `422 Unprocessable Entity`: Invalid schema or constraints (e.g. empty ID, negative balance).

---

### Submit Transfer

```http
POST /transfers
```

**Request**:
```json
{
  "payerId": "acc-payer-1",
  "payeeId": "acc-payee-2",
  "amount": 2500,
  "idempotencyKey": "9c1f8b2e-0000-4000-8000-000000000000"
}
```

**Responses**:
- `201 Created`: Transfer accepted into pending queue for settlement.
- `200 OK`: Duplicate request returning previous transfer state (idempotency hit).
- `422 Unprocessable Entity`: Non-existent account, self-transfer, or schema violation.

**Response Body**:
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "payerId": "acc-payer-1",
  "payeeId": "acc-payee-2",
  "amount": 2500,
  "idempotencyKey": "9c1f8b2e-0000-4000-8000-000000000000",
  "status": "pending",
  "failureReason": null,
  "createdAt": "2026-09-08T14:30:00.000000Z"
}
```

---

### Get Transfer

```http
GET /transfers/{id}
```

**Responses**:
- `200 OK`: Returns transfer details.
- `404 Not Found`: Transfer ID does not exist.

---

### Account Statement

```http
GET /accounts/{id}/statement
```

Returns current balance along with settled transfer entries in reverse chronological order (newest first).

**Responses**:
- `200 OK`:
```json
{
  "accountId": "acc-payer-1",
  "balance": 97500,
  "transfers": [
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "payerId": "acc-payer-1",
      "payeeId": "acc-payee-2",
      "amount": 2500,
      "idempotencyKey": "9c1f8b2e-0000-4000-8000-000000000000",
      "status": "completed",
      "failureReason": null,
      "createdAt": "2026-09-08T14:30:00.000000Z"
    }
  ]
}
```
- `404 Not Found`: Account does not exist.

---

## Configuration

The application is configured using environment variables:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `VESSEL_HOST` | `0.0.0.0` | Bind host address |
| `VESSEL_PORT` | `3000` | HTTP port |
| `VESSEL_BATCH_SIZE` | `512` | Batch size for settlement processing |
| `VESSEL_IDLE_DELAY` | `0.001` | Sleep interval (seconds) when settlement queue is empty |
| `DATABASE_URL` | `None` | PostgreSQL connection DSN. If unset, runs in in-memory mode |
| `VESSEL_WRITE_BATCH_SIZE` | `1000` | Max transfers to flush to DB per batch |
| `VESSEL_WRITE_DELAY` | `0.05` | Flush interval (seconds) for DB persistence |

---

## Development

### Requirements

- Python `3.14`
- [uv](https://github.com/astral-sh/uv) (package and project manager)
- Docker & Docker Compose (for containerized execution and benchmarks)

### Setup

```bash
# Install dependencies into local virtual environment
uv sync
```

### Running Locally

```bash
# In-memory mode (without database)
uv run python -m vessel

# With local PostgreSQL
DATABASE_URL=postgres://rinha:rinha@localhost:5432/rinha?sslmode=disable uv run python -m vessel
```

### Testing & Quality Assurance

```bash
# Run pytest test suite (unit and integration tests)
make test
# or: uv run pytest tests/ -v

# Run type checker (pyright)
uv run pyright

# Run linter and formatting checks (ruff)
make check
# or: uv run ruff check . && uv run ruff format --check .
```

---

## Docker & Deployment

Run the complete stack with PostgreSQL and container resource limits matching the competition specification:

```bash
# Start application and database
docker compose up --build -d

# Check service status and health
docker compose ps

# Follow application logs
docker compose logs -f api
```

### Resource Constraints

Configured in `docker-compose.yml`:
- **API Service**: `1.5 CPU`, `3.0 GB RAM`
- **Database Service**: `0.5 CPU`, `1.0 GB RAM`

---

## Rinha de Backend Benchmark Suite

The repository includes scripts to download and execute official challenge validation suites:

```bash
# Download correctness tests and k6 load tests
make challenge

# Run correctness verification (vitest)
make verify

# Run load test benchmarks (k6: throughput and latency)
make bench
```
