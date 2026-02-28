# 🤖 SRE Multi-Agent Demo (STRATUS-inspired)

> **Autonomous Site Reliability Engineering** cho E-Commerce Microservices  
> Lấy cảm hứng từ paper: _STRATUS — A Multi-agent System for Autonomous Reliability Engineering_

## 📐 Kiến trúc tổng quan

```
┌────────────────────────────────────────────────────────────┐
│                      Client / Dashboard                     │
│                     http://localhost:8888                    │
└─────────────────────────┬──────────────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────────┐
│                 🚪 API Gateway (Nginx :80)                   │
│            /api/orders  /api/products  /api/payments         │
└────────┬──────────────┬──────────────┬─────────────────────┘
         │              │              │
   ┌─────▼─────┐ ┌─────▼──────┐ ┌────▼──────┐
   │ 📦 Order  │ │ 🏷️ Product │ │ 💳 Payment│
   │ Svc :5001 │ │ Svc :5002  │ │ Svc :5003 │
   │ Orchestr. │ │ Catalog    │ │ Payment   │
   └───────────┘ └────────────┘ └───────────┘
         │              │              │
   ┌─────▼──────────────▼──────────────▼────┐
   │          Observability Stack            │
   │  📊 Prometheus :9090                    │
   │  🔍 Jaeger :16686 (Distributed Tracing)│
   │  📈 cAdvisor :8080                      │
   └────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Cài đặt dependencies

```bash
# Agent (chạy trên host machine)
pip install -r requirements.txt

# Tạo file .env
cp .env.example .env
# Sửa OPENAI_API_KEY trong .env
```

### 2. Khởi động microservices + monitoring

```bash
docker compose up --build -d
```

### 3. Kiểm tra hệ thống

```bash
# Health check
curl http://localhost/api/products
curl http://localhost/api/orders

# Tạo đơn hàng (test orchestration)
curl -X POST http://localhost/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": "P001", "qty": 1, "customer_name": "Demo User"}'
```

### 4. Chạy demo

```bash
# Mở Dashboard (tab riêng)
python dashboard/app.py

# Inject lỗi
python scenarios/inject_fault.py --scenario 1  # Bad Nginx config
# hoặc
python scenarios/inject_fault.py --scenario 2  # Payment crash
# hoặc
python scenarios/inject_fault.py --scenario 3  # Product overload

# Chạy SRE Agent (sẽ tự phát hiện & sửa lỗi)
python main_v2.py

# Khôi phục
python scenarios/inject_fault.py --scenario restore
```

## 🤖 Multi-Agent Workflow

```
Triage Agent → Planner Agent → Mitigation Agent → Validation Oracle
     🔍              📋              🔧               🧪
  Detect &        Root Cause       Execute           Post-fix
  Diagnose        Analysis          Fix              Check
                                                       │
                                          ┌─────NO─────┤
                                          ▼            YES → ✅ END
                                     Undo Agent
                                        ⏪
                                   TNR Rollback
                                     (retry?)
```

| Agent | Vai trò | Output (Pydantic) |
|-------|---------|-------------------|
| **Triage** | Thu thập metrics, traces, logs + LLM phân tích | `SymptomList` |
| **Planner** | Xác định root cause, đề xuất action | `MitigationPlan` |
| **Mitigation** | Execute: restart / update config / rollback | `MitigationResult` |
| **Undo (TNR)** | Validate → rollback nếu hệ thống tệ hơn | Circuit Breaker |

## 📊 Observability Endpoints

| Tool | URL | Mô tả |
|------|-----|-------|
| Dashboard | http://localhost:8888 | Service map + Agent log (real-time) |
| Prometheus | http://localhost:9090 | Metrics & PromQL queries |
| Jaeger UI | http://localhost:16686 | Distributed Tracing |
| cAdvisor | http://localhost:8080 | Container resource metrics |

## 🔥 Fault Injection Scenarios

| # | Scenario | Lỗi gì | Agent cần làm |
|---|----------|---------|---------------|
| 1 | Bad Nginx Config | 502 Bad Gateway | Phát hiện qua error rate → LLM sinh config mới |
| 2 | Payment Service Crash | Service unavailable | Health check → restart container |
| 3 | Product Service Overload | High latency | Metrics P95 → restart service |

## 📚 SOA/Microservices Concepts Covered

1. **Bounded Context** — Product / Order / Payment domains
2. **Orchestration** — Order Service gọi Product → Payment  
3. **API Gateway** — Nginx reverse proxy routing
4. **Inter-service Communication** — REST synchronous calls
5. **Distributed Tracing** — OpenTelemetry + Jaeger
6. **Health Checks** — `/health` endpoint mỗi service
7. **Observability** — Prometheus metrics + Jaeger traces + cAdvisor
8. **Circuit Breaker** — TNR max retry limit
9. **Saga / Compensation** — Undo Agent rollback
10. **Chaos Engineering** — Fault injection scenarios
11. **IaC (Infrastructure as Code)** — Docker Compose
12. **AIOps / LLM-driven SRE** — GPT structured output cho diagnosis
13. **Structured Output** — Pydantic schemas giữa agents

## 📁 Project Structure

```
demo-agent/
├── main_v2.py            # 🚀 Entry point
├── graph.py              # LangGraph workflow
├── docker-compose.yml    # Microservices orchestration
├── requirements.txt
├── .env.example
│
├── agents/               # 🤖 Agent modules
│   ├── triage_agent.py   # Hybrid detection
│   ├── planner_agent.py  # Root cause analysis
│   ├── mitigation_agent.py # Execute fixes
│   └── undo_agent.py     # TNR rollback
│
├── models/               # 📦 Data models
│   ├── schemas.py        # Pydantic structured output
│   └── states.py         # TypedDict workflow state
│
├── tools/                # 🔧 LangChain tools
│   ├── docker_tools.py   # Container management
│   ├── metrics_tools.py  # Prometheus queries
│   └── tracing_tools.py  # Jaeger queries
│
├── prompts/              # 💬 LLM prompt templates
│   ├── triage_prompts.py
│   ├── planner_prompts.py
│   └── mitigation_prompts.py
│
├── services/             # 🏗️ Microservices
│   ├── order-service/    # Orchestrator
│   ├── product-service/  # Catalog & stock
│   ├── payment-service/  # Payment processor
│   ├── nginx/            # API Gateway config
│   └── prometheus/       # Monitoring config
│
├── scenarios/            # 🔥 Fault injection
│   └── inject_fault.py
│
└── dashboard/            # 🖥️ Real-time dashboard
    ├── app.py
    └── templates/
        └── index.html
```
