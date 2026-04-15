# CoderBuddy — Deployer Agent & Docker Containerization Task Plan

## Context

Read through this entire task plan before starting. This is an update to the existing CoderBuddy project, NOT a rewrite.

**Repository:** https://github.com/Afrxz/CodeBuddy
**Branch:** master
**Key files:** `coderbuddyv2.py` (main pipeline + FastAPI app), `app.py`

CoderBuddy is a multi-agent code generator with three agents (Planner → Architect → Coder) built with LangGraph, LangChain, CrewAI, and Gemini (via LiteLLM). It takes a natural language prompt and generates a complete project as files on disk, downloadable as a ZIP.

## Objective

Add a **4th agent (Deployer)** to the existing pipeline that takes the generated project files and containerizes them using Docker. The pipeline becomes:

```
Planner → Architect → Coder → Deployer (NEW)
```

## Critical Constraints

- **Do NOT restructure the existing architecture.** The current StateGraph, agent chain, Pydantic models, and FastAPI endpoints must stay intact. You are adding to the pipeline, not rebuilding it.
- **Do NOT change how the existing three agents work.** Their prompts, models, and validation logic should remain untouched.
- **Do NOT change the existing API endpoints.** `/generate` and `/download-zip` must continue to work exactly as before.
- **Docker containerization should be optional.** If Docker is not installed or the user doesn't want it, the existing flow (generate → ZIP) still works perfectly.
- **Keep all changes in as few files as possible.** Ideally the Deployer agent lives in `coderbuddyv2.py` alongside the other agents, following the same patterns.

---

## Task 1: Understand the Existing Codebase

Before writing any code, read and understand the following:

1. Read `coderbuddyv2.py` completely. Understand:
   - How the StateGraph is defined and how agents are chained
   - The Pydantic models used for Plan, TaskPlan, and generated code
   - How the Coder agent writes files to `generated_project_structured/`
   - How the FastAPI endpoints (`/generate`, `/download-zip`) work
   - How rate limiting and retry logic is implemented
2. Read `app.py` to understand if there's a separate frontend entry point
3. Note the exact state schema being passed through the graph — the Deployer agent needs to receive and extend this state, not replace it

**Do not write any code during this task. Just read and confirm you understand the structure.**

---

## Task 2: Define the Deployer Pydantic Models

Add new Pydantic models for the Deployer agent's input and output. Follow the exact same patterns used by the existing Plan and TaskPlan models.

Models to create:

```python
class DockerConfig(BaseModel):
    base_image: str          # e.g., "python:3.11-slim", "node:20-alpine"
    port: int                # e.g., 8000, 3000
    install_command: str     # e.g., "pip install -r requirements.txt"
    run_command: str         # e.g., "uvicorn main:app --host 0.0.0.0 --port 8000"
    env_vars: list[str]      # e.g., ["DATABASE_URL", "API_KEY"]

class DeployerResult(BaseModel):
    dockerfile_content: str
    docker_compose_content: str | None  # only if multi-service
    containerized: bool
    container_name: str
    port: int
```

Place these alongside the existing Pydantic models in the same file.

---

## Task 3: Create the Deployer Agent

Build the Deployer agent following the same pattern as the existing Planner, Architect, and Coder agents. The Deployer agent should:

1. **Receive the generated project files and the Plan** (tech stack, app name, features) from the state
2. **Analyze the project to determine:**
   - What runtime is needed (Python, Node.js, Go, etc.) based on the tech stack in the Plan
   - What the entry point file is
   - What dependencies need to be installed
   - What port the app should expose
3. **Generate a Dockerfile** that:
   - Uses an appropriate slim base image
   - Copies project files
   - Installs dependencies
   - Exposes the correct port
   - Sets the correct CMD/ENTRYPOINT
4. **Generate a docker-compose.yml** if the project has multiple services (e.g., a backend + frontend + database)
5. **Write the Dockerfile and docker-compose.yml** into the `generated_project_structured/` directory alongside the generated code
6. **Optionally build and run the container** if Docker is available on the system

The agent should use the same LLM configuration (Gemini via LiteLLM) and the same rate limiting/retry logic as the other agents.

**Important:** If the LLM fails to generate valid Docker config, the Deployer should gracefully skip containerization and log a warning rather than crashing the entire pipeline.

---

## Task 4: Integrate the Deployer into the StateGraph

Modify the existing LangGraph StateGraph to add the Deployer as the 4th step:

1. Add `deployer_result` (type: `DeployerResult | None`) to the graph state schema
2. Add a `containerize` (type: `bool`, default: `False`) flag to the state to make it optional
3. Add the Deployer node to the graph after the Coder node
4. Add a conditional edge: if `containerize` is True, route to Deployer; otherwise skip to the end node
5. The existing edges (Planner → Architect → Coder) must not change

The state flow becomes:
```
START → Planner → Architect → Coder → [conditional] → Deployer → END
                                       └──────────────────────────→ END
```

---

## Task 5: Add Docker Build/Run Utility Functions

Create utility functions (not part of the agent, just helpers):

```python
def is_docker_available() -> bool:
    """Check if Docker is installed and the daemon is running."""

def build_docker_image(project_dir: str, image_name: str) -> tuple[bool, str]:
    """Build a Docker image from the generated project. Returns (success, logs)."""

def run_docker_container(image_name: str, container_name: str, port: int) -> tuple[bool, str]:
    """Run the Docker container. Returns (success, logs)."""

def stop_docker_container(container_name: str) -> bool:
    """Stop and remove a running container."""
```

These should use `subprocess.run` with proper error handling and timeouts. Place them in the same file or a small `docker_utils.py` if the file is getting too long.

---

## Task 6: Update the FastAPI Endpoints

Add new endpoints while keeping existing ones untouched:

1. **Modify `/generate`** — add an optional `containerize: bool = False` field to the request body. When True, the Deployer agent runs after the Coder. When False (default), behavior is identical to current.

2. **Add `POST /containerize`** — takes an already-generated project and containerizes it after the fact. Useful if the user generated first, then decided they want Docker.

3. **Add `GET /container/status`** — returns whether a container is running, its name, and the port.

4. **Add `POST /container/stop`** — stops a running container.

Existing endpoints (`/generate` with `containerize=False`, `/download-zip`) must behave exactly as they do today.

---

## Task 7: Update the ZIP Download

Modify the `/download-zip` endpoint so that when a project has been containerized, the ZIP includes the Dockerfile and docker-compose.yml alongside the source code. No other changes to the ZIP logic.

---

## Task 8: Update the CLI Mode

If CoderBuddy has a CLI mode (`python coderbuddyv2.py`), add a `--containerize` flag:

```bash
python coderbuddyv2.py                    # existing behavior
python coderbuddyv2.py --containerize     # runs Deployer after Coder
```

If Docker is not available when `--containerize` is used, print a warning and still generate the Dockerfile (so the user can build manually later), but skip the build/run step.

---

## Task 9: Test the Full Pipeline

Test these scenarios manually:

1. **Without containerization** — `POST /generate` with `containerize: false`. Confirm existing behavior is unchanged. All three agents run, files are generated, ZIP works.
2. **With containerization** — `POST /generate` with `containerize: true`. Confirm all four agents run, Dockerfile is generated, and if Docker is available, the container builds and runs.
3. **Docker not available** — `POST /generate` with `containerize: true` but Docker not installed. Confirm the pipeline completes gracefully, Dockerfile is still written to disk, but no build/run attempt.
4. **Different project types** — test with a Python FastAPI prompt, a Node.js Express prompt, and a static HTML prompt to verify the Deployer generates appropriate Dockerfiles for each.
5. **ZIP includes Docker files** — confirm the downloaded ZIP contains the Dockerfile when containerization was requested.

---

## Task 10: Update README

Add a section to the README documenting:

- The new Deployer agent and what it does
- The updated pipeline flow (Planner → Architect → Coder → Deployer)
- The new API endpoints
- The `--containerize` CLI flag
- Docker requirements (Docker must be installed for build/run, but Dockerfile generation works without it)

Update the architecture diagram and flow chart in the README to include the Deployer.

---

## Summary of Files to Modify

| File | Changes |
|------|---------|
| `coderbuddyv2.py` | Add Deployer Pydantic models, Deployer agent, StateGraph update, new endpoints, CLI flag |
| `docker_utils.py` (new, optional) | Docker build/run helper functions if coderbuddyv2.py gets too long |
| `README.md` | Update docs, architecture diagram, new endpoints |

## Do NOT Touch

- Planner agent logic/prompts
- Architect agent logic/prompts
- Coder agent logic/prompts
- Existing Pydantic models (Plan, TaskPlan, etc.)
- Existing `/generate` default behavior
- Existing `/download-zip` default behavior
- Rate limiting and retry logic (reuse it, don't rewrite it)
