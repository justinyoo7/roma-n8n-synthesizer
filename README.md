# ROMA Workflow Synthesizer for n8n

An intelligent workflow synthesis system that transforms natural language descriptions into executable n8n workflows using the ROMA (Recursive Open Meta-Agent) architecture.

## Features

- **Natural Language Input**: Describe your workflow in plain English
- **ROMA Architecture**: Atomizer → Planner → Executor → Aggregator → Verifier → Simplifier
- **n8n Integration**: Automatic workflow creation and deployment via n8n REST API
- **Interactive Graph Viewer**: React Flow-based visualization with node details
- **Automated Testing**: Generate and execute test suites for validation
- **Iterative Refinement**: Automatic improvement loop based on test results
- **Workflow Simplification**: Post-pass optimization to reduce complexity

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  Describe   │  │  Graph View │  │  Version Timeline       │  │
│  │    Page     │  │ (React Flow)│  │                         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Backend (Python FastAPI)                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  ROMA Pipeline                           │    │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────┐          │    │
│  │  │Atomizer│→│Planner │→│Executor│→│Aggregator│          │    │
│  │  └────────┘ └────────┘ └────────┘ └──────────┘          │    │
│  │       │                                │                 │    │
│  │       ▼                                ▼                 │    │
│  │  ┌──────────┐                    ┌──────────┐           │    │
│  │  │ Verifier │                    │Simplifier│           │    │
│  │  └──────────┘                    └──────────┘           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│  ┌──────────────┐  ┌────────┴────────┐  ┌─────────────────┐    │
│  │ n8n Compiler │  │   n8n Client    │  │   Test Harness  │    │
│  └──────────────┘  └─────────────────┘  └─────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    External Services                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   n8n Cloud  │  │   Supabase   │  │   LLM (Claude/GPT)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- n8n Cloud account with API key (or self-hosted n8n)
- Anthropic or OpenAI API key
- Supabase project (for persistence)

### Local Development

1. **Clone and configure**:
   ```bash
   cd roma-n8n-synthesizer
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Start services with Docker Compose**:
   ```bash
   docker-compose up -d
   ```

3. **Access the application**:
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:8000/docs
   - n8n: http://localhost:5678

### Manual Setup (Development)

**Backend**:
```bash
cd synth-engine
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend**:
```bash
cd frontend
npm install
npm run dev
```

## Configuration

### Environment Variables

Create a `.env` file in the root directory:

```env
# LLM Provider
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# n8n Configuration
N8N_BASE_URL=https://your-instance.app.n8n.cloud/api/v1
N8N_API_KEY=your_n8n_api_key

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGc...
SUPABASE_ANON_KEY=eyJhbGc...

# Optional
DEBUG=false
AGENT_RUNNER_TIMEOUT=30
```

### Database Setup

Run the SQL schema in your Supabase SQL editor:
```bash
cat supabase/schema.sql | pbcopy
# Paste in Supabase SQL Editor
```

## API Endpoints

### Synthesis

```http
POST /api/synthesize
Content-Type: application/json

{
  "prompt": "Customer support triage workflow..."
}
```

### Iteration

```http
POST /api/iterate
Content-Type: application/json

{
  "workflow_id": "uuid",
  "iteration_id": "uuid",
  "failure_traces": [],
  "user_feedback": "optional feedback"
}
```

### Simplification

```http
POST /api/simplify
Content-Type: application/json

{
  "workflow_id": "uuid",
  "iteration_id": "uuid"
}
```

## Example: Customer Support Triage

**Input prompt**:
> Customer support triage: Webhook receives {customerMessage}. Classify intent and urgency. If billing issue, draft billing response. If outage report, check status API then draft response. Otherwise, ask clarifying question. Always log to DB and return {category, responseText}.

**Generated workflow**:

```
[Webhook] → [Classifier Agent] → [Switch: category]
                                    ├── billing → [Billing Drafter] ─┐
                                    ├── outage → [Status API] → [Outage Drafter] ─┤
                                    └── other → [Clarification Agent] ─┘
                                                      ↓
                                                [Merge] → [Log to DB] → [Respond]
```

## Scoring System

Workflows are scored on a 0-100 scale:

| Component | Weight | Description |
|-----------|--------|-------------|
| Correctness | 50% | Tests passing |
| Simplicity | 25% | Node/edge count |
| Clarity | 15% | Naming quality |
| Robustness | 10% | Error handling |

**Stopping conditions**:
- All tests pass AND score ≥ 85
- OR no improvement after 2 iterations

## Project Structure

```
roma-n8n-synthesizer/
├── synth-engine/           # Python FastAPI backend
│   ├── app/
│   │   ├── api/           # API endpoints
│   │   ├── roma/          # ROMA pipeline modules
│   │   ├── n8n/           # n8n compiler and client
│   │   ├── llm/           # LLM adapters
│   │   ├── testing/       # Test harness
│   │   └── models/        # Pydantic models
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/               # React frontend
│   ├── src/
│   │   ├── components/    # React Flow nodes, panels
│   │   ├── pages/         # Describe, Workflow pages
│   │   ├── stores/        # Zustand state
│   │   ├── lib/           # API client
│   │   └── types/         # TypeScript types
│   ├── package.json
│   └── Dockerfile
├── supabase/
│   └── schema.sql         # Database schema
├── docker-compose.yml
└── README.md
```

## Security

- API keys are never logged
- Server-side secret management
- Prompt injection detection in agent-runner
- Tool allowlist for agent operations
- Row-level security in Supabase

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest` (backend) and `npm test` (frontend)
5. Submit a pull request

## License

MIT
