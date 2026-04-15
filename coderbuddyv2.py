import os
import json
import subprocess
import argparse
from typing import Optional, Dict, List

from pydantic import BaseModel, Field, ConfigDict
import litellm
from langgraph.graph import StateGraph, END

# NEW: extra stdlib + FastAPI imports for zip download
import shutil
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# ==============================
# 1. Pydantic Models (States)
# ==============================

class File(BaseModel):
    path: str = Field(description="The path to the file to be created or modified")
    purpose: str = Field(description="The purpose of the file, e.g. 'main application logic', 'data processing module', etc.")


class Plan(BaseModel):
    name: str = Field(description="The name of app to be built")
    description: str = Field(description="A oneline description of the app to be built, e.g. 'A web application for managing personal finances'")
    techstack: str = Field(description="The tech stack to be used for the app, e.g. 'python', 'javascript', 'react', 'flask', etc.")
    features: list[str] = Field(description="A list of features that the app should have, e.g. 'user authentication', 'data visualization', etc.")
    files: list[File] = Field(description="A list of files to be created, each with a 'path' and 'purpose'")


class ImplementationTask(BaseModel):
    filepath: str = Field(description="The path to the file to be modified")
    task_description: str = Field(description="A detailed description of the task to be performed on the file, e.g. 'add user authentication', 'implement data processing logic', etc.")


class TaskPlan(BaseModel):
    implementation_steps: list[ImplementationTask] = Field(description="A list of steps to be taken to implement the task")
    model_config = ConfigDict(extra="allow")


class CoderState(BaseModel):
    task_plan: TaskPlan = Field(description="The plan for the task to be implemented")
    current_step_idx: int = Field(0, description="The index of the current step in the implementation steps")
    current_file_content: Optional[str] = Field(None, description="The content of the file currently being edited or created")


class DockerConfig(BaseModel):
    base_image: str = Field(description="Docker base image, e.g. 'python:3.11-slim', 'node:20-alpine'")
    port: int = Field(description="Port to expose, e.g. 8000, 3000")
    install_command: str = Field(description="Command to install dependencies, e.g. 'pip install -r requirements.txt'")
    run_command: str = Field(description="Command to run the app, e.g. 'uvicorn main:app --host 0.0.0.0 --port 8000'")
    env_vars: list[str] = Field(default_factory=list, description="Environment variable names, e.g. ['DATABASE_URL', 'API_KEY']")


class DeployerResult(BaseModel):
    dockerfile_content: str = Field(description="Generated Dockerfile content")
    docker_compose_content: Optional[str] = Field(None, description="Generated docker-compose.yml content, only if multi-service")
    containerized: bool = Field(False, description="Whether the container was actually built and run")
    container_name: str = Field(description="Name of the Docker container")
    port: int = Field(description="Port the container exposes")


# ==============================
# 2. LLM Setup (via LiteLLM)
# ==============================

# Default config — can be changed at runtime via /set-api-key
llm_config = {
    "model": "gemini/gemini-2.0-flash",
    "temperature": 0.1,
}

# Set default API key (Gemini)
os.environ["GOOGLE_API_KEY"] = "AIzaSyC2qpicvwm6Ws0dfEFOt6LPibhSws5B-EE"


def llm_call(prompt: str) -> str:
    """Call the LLM via LiteLLM and return the response text."""
    kwargs = {
        "model": llm_config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": llm_config["temperature"],
    }

    # LiteLLM routes DeepSeek to /beta by default — override to the correct base URL
    provider = llm_config["model"].split("/")[0] if "/" in llm_config["model"] else ""
    if provider == "deepseek":
        kwargs["api_base"] = "https://api.deepseek.com"

    response = litellm.completion(**kwargs)
    return response.choices[0].message.content


def update_llm(api_key: str, model: str = "gemini/gemini-2.0-flash", temperature: float = 0.1):
    """Update the LLM configuration and API key at runtime."""
    llm_config["model"] = model
    llm_config["temperature"] = temperature

    # Set the right env var based on provider prefix
    provider = model.split("/")[0] if "/" in model else ""
    if provider == "groq":
        os.environ["GROQ_API_KEY"] = api_key
    elif provider == "gemini":
        os.environ["GOOGLE_API_KEY"] = api_key
    elif provider == "deepseek":
        os.environ["DEEPSEEK_API_KEY"] = api_key
    elif provider in ("gpt", "openai") or model.startswith("gpt-"):
        os.environ["OPENAI_API_KEY"] = api_key
    else:
        # Fallback: set all common env vars
        os.environ["GOOGLE_API_KEY"] = api_key
        os.environ["GROQ_API_KEY"] = api_key
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["DEEPSEEK_API_KEY"] = api_key


# ==============================
# 3. Prompt Helpers
# ==============================

def planner_prompt(user_prompt: str) -> str:
    return f"""
You are the PLANNER agent. Convert the user prompt into a COMPLETE engineering project plan
in STRICT JSON following this schema:

{{
  "name": "string - the name of the app",
  "description": "string - one-line description of the app",
  "techstack": "string - tech stack, e.g. 'html/css/js', 'react + fastapi', 'python cli', etc.",
  "features": ["list", "of", "features"],
  "files": [
    {{
      "path": "string - file path, e.g. 'index.html', 'style.css', 'script.js', 'main.py'",
      "purpose": "string - purpose of this file"
    }}
  ]
}}

RULES:
- Respond with JSON ONLY. No backticks, no prose.
- Make sure the JSON is valid and matches the schema above.

User request:
{user_prompt}
""".strip()


def architect_prompt(plan_json: str) -> str:
    return f"""
You are the ARCHITECT agent. Given this project Plan (as JSON), create a TaskPlan of implementation steps.

The TaskPlan must follow this STRICT JSON schema:

{{
  "implementation_steps": [
    {{
      "filepath": "string - a file path from the Plan.files list",
      "task_description": "string - a detailed task for implementing or updating that file"
    }}
  ]
}}

Guidelines:
- Create multiple implementation_steps, covering all files that need work.
- Each step should be concrete and actionable.
- Group related work by file, but you may have multiple steps per file.
- Do NOT add other top-level fields than 'implementation_steps' (extra is allowed, but not necessary).

Plan (JSON):
{plan_json}

Respond with JSON ONLY. No backticks, no prose.
""".strip()


def coder_system_prompt() -> str:
    return """
You are the CODER agent.
You are implementing a specific engineering task: generating the FULL contents of ONE file.

Always:
- Implement the FULL file content, not snippets.
- Maintain consistent naming of variables, functions, and imports.
- Ensure imports refer to the filenames given by the architect.
- Make the file self-contained and runnable/usable given the rest of the project.
""".strip()


# ==============================
# 4. Utility Helpers
# ==============================

def extract_json(text: str):
    """
    Extract a JSON object from text, even if the model adds extra text or markdown fences.
    Returns a Python dict.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object detected", text, 0)
    json_str = text[start : end + 1]
    return json.loads(json_str)


def extract_code(text: str) -> str:
    """
    Strip markdown code fences if present and return just the code.
    Works for ```python ... ``` or ``` ... ``` blocks.
    """
    if "```" not in text:
        return text

    parts = text.split("```")
    if len(parts) >= 3:
        body = parts[1]
        lines = body.splitlines()
        if len(lines) > 0 and len(lines[0]) < 20:
            return "\n".join(lines[1:])
        return body
    return text


# ==============================
# 5. Docker Utility Functions
# ==============================

def is_docker_available() -> bool:
    """Check if Docker is installed and the daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def build_docker_image(project_dir: str, image_name: str) -> tuple:
    """Build a Docker image from the generated project. Returns (success, logs)."""
    try:
        result = subprocess.run(
            ["docker", "build", "-t", image_name, "."],
            cwd=project_dir,
            capture_output=True, text=True, timeout=300
        )
        return (result.returncode == 0, result.stdout + result.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return (False, str(e))


def run_docker_container(image_name: str, container_name: str, port: int) -> tuple:
    """Run the Docker container. Returns (success, logs)."""
    try:
        # Stop existing container with same name if any
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, text=True, timeout=10
        )
        result = subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "-p", f"{port}:{port}", image_name],
            capture_output=True, text=True, timeout=30
        )
        return (result.returncode == 0, result.stdout + result.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return (False, str(e))


def stop_docker_container(container_name: str) -> bool:
    """Stop and remove a running container."""
    try:
        result = subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_container_status(container_name: str) -> dict:
    """Get the status of a Docker container."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return {"running": result.stdout.strip() == "running", "status": result.stdout.strip()}
        return {"running": False, "status": "not found"}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"running": False, "status": "docker unavailable"}


# ==============================
# 5b. Deployer Prompt
# ==============================

def deployer_prompt(plan_json: str, file_list: str) -> str:
    return f"""
You are the DEPLOYER agent. Given a project Plan and list of generated files, create a Docker configuration.

Analyze the project and respond with STRICT JSON following this schema:

{{
  "base_image": "string - appropriate slim Docker base image, e.g. 'python:3.11-slim', 'node:20-alpine', 'nginx:alpine'",
  "port": "integer - the port the app should expose",
  "install_command": "string - command to install dependencies, e.g. 'pip install -r requirements.txt', 'npm install'",
  "run_command": "string - command to run the app, e.g. 'python app.py', 'node server.js', 'nginx -g daemon off;'",
  "env_vars": ["list", "of", "env", "var", "names"]
}}

RULES:
- Respond with JSON ONLY. No backticks, no prose.
- Choose the base image based on the tech stack.
- For static HTML/CSS/JS projects, use 'nginx:alpine' as base image, port 80, and no install command (use 'echo ok').
- For Python projects, use 'python:3.11-slim'.
- For Node.js projects, use 'node:20-alpine'.
- Pick the run command based on the entry point file and framework.

Project Plan:
{plan_json}

Generated Files:
{file_list}
""".strip()


# ==============================
# 6. LangGraph Node Functions
# ==============================

def planner_agent(state: dict) -> dict:
    """Converts user prompt into a structured Plan."""
    user_prompt: str = state["user_prompt"]

    resp_text = llm_call(planner_prompt(user_prompt))
    try:
        plan_dict = extract_json(resp_text)
        plan = Plan.model_validate(plan_dict)
    except Exception:
        print("\n[!] Failed to parse Plan JSON, falling back to minimal Plan.")
        print("Raw planner output:\n", resp_text)
        plan = Plan(
            name="Generated App",
            description=user_prompt[:100],
            techstack="unspecified",
            features=[],
            files=[],
        )

    return {"plan": plan}


def architect_agent(state: dict) -> dict:
    """Creates TaskPlan from Plan."""
    plan: Plan = state["plan"]

    resp_text = llm_call(architect_prompt(plan.model_dump_json()))
    try:
        tp_dict = extract_json(resp_text)
        task_plan = TaskPlan.model_validate(tp_dict)
    except Exception:
        print("\n[!] Failed to parse TaskPlan JSON, falling back to empty TaskPlan.")
        print("Raw architect output:\n", resp_text)
        task_plan = TaskPlan(implementation_steps=[])

    # keep plan in state
    return {"plan": plan, "task_plan": task_plan}


def coder_agent(state: dict) -> dict:
    """
    Coder agent: uses Plan + TaskPlan to generate full contents of each file
    and writes them to disk. Uses CoderState but in a simple "all done" way.
    """
    plan: Plan = state["plan"]
    task_plan: TaskPlan = state["task_plan"]

    tasks_by_file: Dict[str, List[ImplementationTask]] = {}
    for step in task_plan.implementation_steps:
        tasks_by_file.setdefault(step.filepath, []).append(step)

    file_purpose_map = {f.path: f.purpose for f in plan.files}
    generated_code: Dict[str, str] = {}

    for filepath, steps in tasks_by_file.items():
        steps_text = "\n".join(f"- {s.task_description}" for s in steps)
        purpose = file_purpose_map.get(filepath, "No explicit purpose provided")

        prompt = f"""
{coder_system_prompt()}

You are generating the COMPLETE contents of the file: `{filepath}`.

App name: {plan.name}
Description: {plan.description}
Tech stack: {plan.techstack}
Features: {", ".join(plan.features)}

File purpose: {purpose}

Implementation steps for this file:
{steps_text}

Requirements:
- Generate the FULL contents of `{filepath}`.
- Make sure it fits naturally into the overall project.
- If this is a UI file (e.g., HTML), include realistic structure and necessary includes.
- If this is a script/module, include imports, functions, and classes as needed.

Return ONLY the file contents (no explanations, no markdown fences).
""".strip()

        code_text = llm_call(prompt)
        generated_code[filepath] = code_text

    output_dir = "generated_project_structured"
    os.makedirs(output_dir, exist_ok=True)

    for filepath, code_text in generated_code.items():
        safe_code = extract_code(code_text)
        full_path = os.path.join(output_dir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(safe_code)
        print(f"[OK] Wrote {full_path}")

    coder_state = CoderState(
        task_plan=task_plan,
        current_step_idx=len(task_plan.implementation_steps),
        current_file_content=None,
    )

    # RETURN EVERYTHING NEEDED IN FINAL STATE
    return {
        "plan": plan,
        "task_plan": task_plan,
        "coder_state": coder_state,
        "code": generated_code,
    }


def deployer_agent(state: dict) -> dict:
    """
    Deployer agent: analyzes generated project and creates Docker configuration.
    Writes Dockerfile and optionally docker-compose.yml to the project directory.
    If Docker is available, builds and runs the container.
    """
    plan: Plan = state["plan"]
    code: Dict[str, str] = state.get("code", {})

    file_list = "\n".join(f"- {path}" for path in code.keys())

    # Ask the LLM for Docker config
    resp_text = llm_call(deployer_prompt(plan.model_dump_json(), file_list))
    try:
        config_dict = extract_json(resp_text)
        docker_config = DockerConfig.model_validate(config_dict)
    except Exception:
        print("\n[WARN] Failed to parse DockerConfig JSON, skipping containerization.")
        print("Raw deployer output:\n", resp_text)
        return {
            **state,
            "deployer_result": DeployerResult(
                dockerfile_content="",
                docker_compose_content=None,
                containerized=False,
                container_name="",
                port=0,
            ),
        }

    # Generate Dockerfile content
    container_name = f"codebuddy-{plan.name.lower().replace(' ', '-')}"
    env_lines = "\n".join(f"ENV {var}=" for var in docker_config.env_vars) if docker_config.env_vars else ""

    dockerfile_content = f"""FROM {docker_config.base_image}

WORKDIR /app

COPY . .

{env_lines}

RUN {docker_config.install_command}

EXPOSE {docker_config.port}

CMD {json.dumps(docker_config.run_command.split())}
"""

    # Generate docker-compose.yml
    docker_compose_content = f"""version: '3.8'

services:
  app:
    build: .
    container_name: {container_name}
    ports:
      - "{docker_config.port}:{docker_config.port}"
    restart: unless-stopped
"""

    # Write Docker files to project directory
    output_dir = "generated_project_structured"
    os.makedirs(output_dir, exist_ok=True)

    dockerfile_path = os.path.join(output_dir, "Dockerfile")
    with open(dockerfile_path, "w", encoding="utf-8") as f:
        f.write(dockerfile_content)
    print(f"[OK] Wrote {dockerfile_path}")

    compose_path = os.path.join(output_dir, "docker-compose.yml")
    with open(compose_path, "w", encoding="utf-8") as f:
        f.write(docker_compose_content)
    print(f"[OK] Wrote {compose_path}")

    # Try to build and run if Docker is available
    containerized = False
    if is_docker_available():
        print("[DOCKER] Docker detected, building image...")
        image_name = container_name
        success, logs = build_docker_image(output_dir, image_name)
        if success:
            print(f"[OK] Docker image '{image_name}' built successfully.")
            run_success, run_logs = run_docker_container(image_name, container_name, docker_config.port)
            if run_success:
                print(f"[OK] Container '{container_name}' running on port {docker_config.port}.")
                containerized = True
            else:
                print(f"[WARN] Failed to run container: {run_logs}")
        else:
            print(f"[WARN] Failed to build Docker image: {logs}")
    else:
        print("[WARN] Docker not available. Dockerfile written but skipping build/run.")

    deployer_result = DeployerResult(
        dockerfile_content=dockerfile_content,
        docker_compose_content=docker_compose_content,
        containerized=containerized,
        container_name=container_name,
        port=docker_config.port,
    )

    return {**state, "deployer_result": deployer_result}


# ==============================
# 7. Build the LangGraph Agent
# ==============================

def should_containerize(state: dict) -> str:
    """Conditional edge: route to deployer if containerize flag is set."""
    if state.get("containerize", False):
        return "deployer"
    return END


graph = StateGraph(dict)

graph.add_node("planner", planner_agent)
graph.add_node("architect", architect_agent)
graph.add_node("coder", coder_agent)
graph.add_node("deployer", deployer_agent)

graph.add_edge("planner", "architect")
graph.add_edge("architect", "coder")
graph.add_conditional_edges("coder", should_containerize, {"deployer": "deployer", END: END})
graph.add_edge("deployer", END)

graph.set_entry_point("planner")
agent = graph.compile()


# ==============================
# 8. FastAPI Layer
# ==============================

app = FastAPI(title="Coder Buddy Generator", version="1.0.0")

# allow all origins so you can call from a frontend easily (Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/response models for the API

class GenerateRequest(BaseModel):
    prompt: str = Field(description="User prompt describing the app to generate")
    containerize: bool = Field(False, description="Whether to run the Deployer agent for Docker containerization")


class GeneratedFile(BaseModel):
    path: str
    content: str


class DeployerResultResponse(BaseModel):
    dockerfile_content: str = ""
    docker_compose_content: Optional[str] = None
    containerized: bool = False
    container_name: str = ""
    port: int = 0


class GenerateResponse(BaseModel):
    plan: Plan
    task_plan: TaskPlan
    files: List[GeneratedFile]
    deployer_result: Optional[DeployerResultResponse] = None


# Store last result for /containerize endpoint
_last_result: Dict = {}


@app.post("/generate", response_model=GenerateResponse)
def generate_project(req: GenerateRequest):
    """
    Run the planner -> architect -> coder pipeline for the given prompt,
    write the project to disk, and return the structured plan + tasks + files.
    Optionally runs the Deployer agent if containerize=True.
    """
    global _last_result
    try:
        result = agent.invoke(
            {"user_prompt": req.prompt, "containerize": req.containerize},
            {"recursion_limit": 100},
        )
    except Exception as e:
        error_msg = str(e)
        # Surface the actual LLM error to the user
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {error_msg}")
    _last_result = result

    plan: Plan = result["plan"]
    task_plan: TaskPlan = result["task_plan"]
    code: Dict[str, str] = result.get("code", {})

    files = [GeneratedFile(path=p, content=c) for p, c in code.items()]

    deployer_resp = None
    if req.containerize and result.get("deployer_result"):
        dr: DeployerResult = result["deployer_result"]
        deployer_resp = DeployerResultResponse(
            dockerfile_content=dr.dockerfile_content,
            docker_compose_content=dr.docker_compose_content,
            containerized=dr.containerized,
            container_name=dr.container_name,
            port=dr.port,
        )

    return GenerateResponse(plan=plan, task_plan=task_plan, files=files, deployer_result=deployer_resp)


@app.post("/containerize")
def containerize_project():
    """
    Containerize an already-generated project.
    Must call POST /generate first.
    """
    global _last_result
    if not _last_result or "plan" not in _last_result:
        raise HTTPException(status_code=400, detail="No project generated yet. Call POST /generate first.")

    # Run deployer agent on the existing state
    state = {**_last_result, "containerize": True}
    deployer_state = deployer_agent(state)
    _last_result = deployer_state

    dr: DeployerResult = deployer_state["deployer_result"]
    return DeployerResultResponse(
        dockerfile_content=dr.dockerfile_content,
        docker_compose_content=dr.docker_compose_content,
        containerized=dr.containerized,
        container_name=dr.container_name,
        port=dr.port,
    )


@app.get("/container/status")
def container_status():
    """Returns whether a container is running, its name, and port."""
    if not _last_result or "deployer_result" not in _last_result or not _last_result["deployer_result"]:
        return {"running": False, "container_name": "", "port": 0, "status": "no container"}

    dr: DeployerResult = _last_result["deployer_result"]
    if not dr.container_name:
        return {"running": False, "container_name": "", "port": 0, "status": "no container"}

    status = get_container_status(dr.container_name)
    return {
        "running": status["running"],
        "container_name": dr.container_name,
        "port": dr.port,
        "status": status["status"],
    }


@app.post("/container/stop")
def container_stop():
    """Stop a running container."""
    if not _last_result or "deployer_result" not in _last_result or not _last_result["deployer_result"]:
        raise HTTPException(status_code=400, detail="No container to stop.")

    dr: DeployerResult = _last_result["deployer_result"]
    if not dr.container_name:
        raise HTTPException(status_code=400, detail="No container name available.")

    success = stop_docker_container(dr.container_name)
    if success:
        return {"message": f"Container '{dr.container_name}' stopped and removed."}
    raise HTTPException(status_code=500, detail=f"Failed to stop container '{dr.container_name}'.")


class SetApiKeyRequest(BaseModel):
    api_key: str = Field(description="The API key for the LLM provider")
    model: str = Field("gemini/gemini-2.0-flash", description="LLM model identifier")
    temperature: float = Field(0.1, description="LLM temperature (0.0 - 1.0)")


@app.post("/set-api-key")
def set_api_key(req: SetApiKeyRequest):
    """Update the LLM API key and model configuration at runtime."""
    update_llm(api_key=req.api_key, model=req.model, temperature=req.temperature)
    return {"message": "API key and model configuration updated successfully.", "model": req.model}


@app.get("/get-config")
def get_config():
    """Return the current LLM configuration (key is masked)."""
    model = llm_config["model"]
    provider = model.split("/")[0] if "/" in model else ""
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY", "")
    elif provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY", "")
    elif provider in ("gpt", "openai") or model.startswith("gpt-"):
        key = os.environ.get("OPENAI_API_KEY", "")
    else:
        key = os.environ.get("GOOGLE_API_KEY", "")
    masked = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return {"api_key_masked": masked, "model": model, "temperature": llm_config["temperature"]}


# NEW: Endpoint to download the generated project as a ZIP
@app.get("/download-zip")
def download_project_zip():
    """
    Zip the 'generated_project_structured' folder and return it as a file download.

    Usage:
        - First call POST /generate to create a project.
        - Then call GET /download-zip to download generated_project_structured.zip
    """
    folder = "generated_project_structured"
    if not os.path.isdir(folder):
        raise HTTPException(
            status_code=404,
            detail="Project folder not found. Generate a project first using POST /generate.",
        )

    # This will create 'generated_project_structured.zip' in the current directory
    zip_base_name = "generated_project_structured"
    zip_path = shutil.make_archive(zip_base_name, "zip", folder)

    return FileResponse(
        path=zip_path,
        filename=os.path.basename(zip_path),
        media_type="application/zip",
    )


# ==============================
# 9. CLI entrypoint
# ==============================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coder Buddy – Multi-Agent Code Generator")
    parser.add_argument("--containerize", action="store_true", help="Run the Deployer agent to containerize the generated project with Docker")
    args = parser.parse_args()

    user_prompt = input("What coding project do you want me to help with? ")

    invoke_input = {"user_prompt": user_prompt, "containerize": args.containerize}
    result = agent.invoke(invoke_input, {"recursion_limit": 100})

    print("\n=== PLAN (structured) ===")
    plan: Plan = result["plan"]
    print(plan.model_dump_json(indent=2))

    print("\n=== TASK PLAN (structured) ===")
    task_plan: TaskPlan = result["task_plan"]
    print(task_plan.model_dump_json(indent=2))

    print("\n=== GENERATED CODE (in-memory) ===")
    for path, content in result.get("code", {}).items():
        print(f"\n--- {path} ---\n{content[:400]}{'...' if len(content) > 400 else ''}")

    print("\n=== CODER STATE ===")
    coder_state: CoderState = result["coder_state"]
    print(coder_state.model_dump_json(indent=2))

    if args.containerize and result.get("deployer_result"):
        dr: DeployerResult = result["deployer_result"]
        print("\n=== DEPLOYER RESULT ===")
        print(f"Container name: {dr.container_name}")
        print(f"Port: {dr.port}")
        print(f"Containerized: {dr.containerized}")
        print(f"Dockerfile written to generated_project_structured/Dockerfile")
        if dr.docker_compose_content:
            print(f"docker-compose.yml written to generated_project_structured/docker-compose.yml")

    print(f"\nAll files saved under: {os.path.abspath('generated_project_structured')}")


#uvicorn coderbuddyv2:app --reload