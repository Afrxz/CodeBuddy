# CoderBuddy v2

A multi-agent AI code generator that takes a natural language prompt and generates a complete, downloadable project. Built with **LangGraph**, **LiteLLM**, and **FastAPI**.

## Architecture

```
User Prompt
    |
    v
[Planner Agent]  -->  Generates project plan (name, tech stack, features, files)
    |
    v
[Architect Agent]  -->  Creates implementation steps for each file
    |
    v
[Coder Agent]  -->  Generates full source code for every file
    |
    v
[Deployer Agent]  -->  (Optional) Generates Dockerfile & docker-compose.yml
    |
    v
  Output: Project files on disk + ZIP download
```

## Features

- **4-Agent Pipeline** — Planner, Architect, Coder, and Deployer agents work in sequence
- **Multi-Provider LLM Support** — Switch between providers at runtime via the UI:
  - **Groq** — Llama 3.3 70B, Llama 4 Scout, GPT-OSS, Qwen3, and more
  - **Gemini** — Gemini 2.0 Flash, 1.5 Flash, 1.5 Pro
  - **OpenAI** — GPT-4o, GPT-4o-mini, GPT-3.5 Turbo
  - **DeepSeek** — DeepSeek Chat (V3), DeepSeek Reasoner (R1)
- **Docker Containerization** — Optional Deployer agent generates Dockerfile and docker-compose.yml, with auto-build/run if Docker is installed
- **Streamlit UI** — Full web interface with sidebar for API key/model configuration
- **FastAPI Backend** — RESTful API with endpoints for generation, containerization, and container management
- **ZIP Download** — Download the full generated project (including Docker files) as a ZIP

## Getting Started

### Prerequisites

- Python 3.10+
- An API key for at least one provider (Groq, Gemini, OpenAI, or DeepSeek)
- Docker (optional, for container build/run)

### Installation

```bash
pip install litellm langgraph pydantic fastapi uvicorn streamlit requests
```

### Running the App

**1. Start the FastAPI backend:**

```bash
uvicorn coderbuddyv2:app --reload --port 8000
```

**2. Start the Streamlit frontend:**

```bash
streamlit run app.py --server.port 8501
```

**3. Open the UI:**

- Frontend: http://localhost:8501
- API docs: http://localhost:8000/docs

**4. Configure your API key:**

Use the sidebar in the Streamlit UI to select a provider, enter your API key, choose a model, and click **Save Configuration**.

### CLI Mode

```bash
# Standard generation
python coderbuddyv2.py

# With Docker containerization
python coderbuddyv2.py --containerize
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/generate` | Run the full pipeline. Body: `{"prompt": "...", "containerize": false}` |
| `POST` | `/containerize` | Containerize an already-generated project |
| `GET` | `/download-zip` | Download the generated project as a ZIP |
| `GET` | `/container/status` | Check if a container is running |
| `POST` | `/container/stop` | Stop a running container |
| `POST` | `/set-api-key` | Update LLM provider/model/key at runtime |
| `GET` | `/get-config` | Get current LLM configuration (key masked) |

## Project Structure

```
newcoderbuddy/
  coderbuddyv2.py          # Main backend — agents, LangGraph pipeline, FastAPI, CLI
  app.py                    # Streamlit frontend UI
  generated_project_structured/  # Output directory for generated projects
  CODEBUDDY_DEPLOYER_TASKPLAN.md # Original task plan for the Deployer agent
  README.md                 # This file
```

## How It Works

1. **Planner Agent** — Takes the user prompt and produces a structured plan: app name, description, tech stack, features, and a list of files to create.

2. **Architect Agent** — Takes the plan and breaks it into concrete implementation steps for each file.

3. **Coder Agent** — Generates the full source code for every file, writes them to `generated_project_structured/`.

4. **Deployer Agent** *(optional)* — Analyzes the generated project and creates:
   - A `Dockerfile` with the appropriate base image, dependencies, and run command
   - A `docker-compose.yml` for easy container management
   - If Docker is installed, automatically builds the image and runs the container

## Tech Stack

- **LangGraph** — Agent orchestration via StateGraph
- **LiteLLM** — Unified LLM interface (Groq, Gemini, OpenAI, DeepSeek)
- **FastAPI** — Backend REST API
- **Streamlit** — Frontend web UI
- **Pydantic** — Data validation and state models
