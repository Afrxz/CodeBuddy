import json
import requests
import streamlit as st

# Change this if your API is at a different host/port
API_BASE_URL = "http://127.0.0.1:8000"


def call_generate_api(prompt: str, containerize: bool = False) -> dict:
    """Call the FastAPI /generate endpoint."""
    url = f"{API_BASE_URL}/generate"
    payload = {"prompt": prompt, "containerize": containerize}
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()


def call_containerize_api() -> dict:
    """Call the FastAPI /containerize endpoint."""
    url = f"{API_BASE_URL}/containerize"
    resp = requests.post(url)
    resp.raise_for_status()
    return resp.json()


def call_container_status_api() -> dict:
    """Call the FastAPI /container/status endpoint."""
    url = f"{API_BASE_URL}/container/status"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


def call_container_stop_api() -> dict:
    """Call the FastAPI /container/stop endpoint."""
    url = f"{API_BASE_URL}/container/stop"
    resp = requests.post(url)
    resp.raise_for_status()
    return resp.json()


def call_download_zip() -> bytes:
    """Call the FastAPI /download-zip endpoint and return the ZIP bytes."""
    url = f"{API_BASE_URL}/download-zip"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.content


def call_set_api_key(api_key: str, model: str, temperature: float) -> dict:
    """Call the FastAPI /set-api-key endpoint."""
    url = f"{API_BASE_URL}/set-api-key"
    payload = {"api_key": api_key, "model": model, "temperature": temperature}
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()


def call_get_config() -> dict:
    """Call the FastAPI /get-config endpoint."""
    url = f"{API_BASE_URL}/get-config"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


def main():
    st.set_page_config(page_title="Coder Buddy UI", layout="wide")

    # -----------------------
    #   SIDEBAR – API Config
    # -----------------------
    with st.sidebar:
        st.header("🔑 API Configuration")

        # Fetch current config from backend
        current_config = {}
        try:
            current_config = call_get_config()
        except requests.RequestException:
            st.warning("Could not fetch current config from backend.")

        st.caption(f"Current key: `{current_config.get('api_key_masked', '****')}`")
        st.caption(f"Current model: `{current_config.get('model', 'N/A')}`")

        st.divider()

        api_key = st.text_input(
            "API Key",
            type="password",
            placeholder="Enter your API key",
            help="Your API key for the selected provider (Groq, Gemini, or OpenAI)",
        )

        provider = st.selectbox(
            "Provider",
            options=["Groq", "Gemini", "OpenAI", "DeepSeek"],
            index=0,
            help="Select the LLM provider",
        )

        provider_models = {
            "Groq": [
                "groq/llama-3.3-70b-versatile",
                "groq/llama-3.1-8b-instant",
                "groq/meta-llama/llama-4-scout-17b-16e-instruct",
                "groq/openai/gpt-oss-120b",
                "groq/openai/gpt-oss-20b",
                "groq/qwen/qwen3-32b",
                "groq/groq/compound",
                "groq/groq/compound-mini",
            ],
            "Gemini": [
                "gemini/gemini-2.0-flash",
                "gemini/gemini-1.5-flash",
                "gemini/gemini-1.5-pro",
            ],
            "OpenAI": [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-3.5-turbo",
            ],
            "DeepSeek": [
                "deepseek/deepseek-chat",
                "deepseek/deepseek-reasoner",
            ],
        }

        model = st.selectbox(
            "Model",
            options=provider_models.get(provider, []),
            index=0,
            help="Select the LLM model to use for code generation",
        )

        temperature = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=1.0,
            value=0.1,
            step=0.05,
            help="Lower = more deterministic, higher = more creative",
        )

        if st.button("💾 Save Configuration", use_container_width=True):
            if not api_key.strip():
                st.error("Please enter an API key.")
            else:
                try:
                    result = call_set_api_key(api_key.strip(), model, temperature)
                    st.success(f"Configuration saved! Model: `{result.get('model')}`")
                except requests.RequestException as e:
                    st.error(f"Failed to update: {e}")

        st.divider()
        st.caption("The API key is sent to the backend and used for LLM calls. It is not stored on disk.")

    # -----------------------
    #   MAIN CONTENT
    # -----------------------
    st.title("🤖 Coder Buddy – Project Generator")

    st.markdown(
        "This Streamlit app talks to your **FastAPI Coder Buddy** backend.\n\n"
        "1. Enter a description of the app you want.\n"
        "2. Click **Generate Project** – it calls `POST /generate`.\n"
        "3. Inspect the plan, tasks, and generated files.\n"
        "4. Download the full project as a ZIP via `GET /download-zip`."
    )

    # Keep last result across reruns
    if "last_result" not in st.session_state:
        st.session_state.last_result = None

    # --- Prompt input ---
    st.subheader("1️⃣ Describe your app")
    prompt = st.text_area(
        "Prompt",
        value="Build a colourful modern todo app in html css and js",
        height=120,
    )

    containerize = st.checkbox("🐳 Containerize with Docker", value=False,
                               help="Run the Deployer agent to generate a Dockerfile and optionally build/run the container")

    col_generate, col_clear = st.columns([1, 0.3])
    with col_generate:
        generate_clicked = st.button("🚀 Generate Project", type="primary")
    with col_clear:
        if st.button("Clear result"):
            st.session_state.last_result = None

    if generate_clicked:
        if not prompt.strip():
            st.warning("Please enter a prompt first.")
        else:
            with st.spinner("Calling Coder Buddy API..."):
                try:
                    data = call_generate_api(prompt.strip(), containerize=containerize)
                    st.session_state.last_result = data
                    st.success("Project generated successfully!")
                except requests.RequestException as e:
                    # Try to extract the detail message from the backend
                    detail = ""
                    if hasattr(e, "response") and e.response is not None:
                        try:
                            detail = e.response.json().get("detail", "")
                        except Exception:
                            pass
                    if detail:
                        st.error(f"Error: {detail}")
                    else:
                        st.error(f"API request failed: {e}")

    data = st.session_state.last_result

    # If we have a result, show it
    if data:
        plan = data.get("plan")
        task_plan = data.get("task_plan")
        files = data.get("files", [])

        # -----------------------
        #   PLAN
        # -----------------------
        st.subheader("2️⃣ Plan")
        if plan:
            cols = st.columns(2)
            with cols[0]:
                st.markdown(f"**Name:** {plan.get('name', '')}")
                st.markdown(f"**Tech stack:** `{plan.get('techstack', '')}`")
            with cols[1]:
                st.markdown("**Description:**")
                st.write(plan.get("description", ""))

            st.markdown("**Features:**")
            feats = plan.get("features", [])
            if feats:
                for f in feats:
                    st.markdown(f"- {f}")
            else:
                st.write("No features listed.")

            st.markdown("**Planned Files:**")
            plan_files = plan.get("files", [])
            if plan_files:
                for f in plan_files:
                    st.markdown(f"- `{f.get('path')}` – {f.get('purpose')}")
            else:
                st.write("No files in plan.")
        else:
            st.write("No plan returned from API.")

        # -----------------------
        #   TASK PLAN
        # -----------------------
        st.subheader("3️⃣ Task Plan (Implementation Steps)")
        if task_plan and task_plan.get("implementation_steps"):
            steps = task_plan["implementation_steps"]
            for i, step in enumerate(steps, start=1):
                st.markdown(
                    f"**Step {i}:** `{step.get('filepath')}` – {step.get('task_description')}"
                )
        else:
            st.write("No task plan available.")

        # -----------------------
        #   FILES
        # -----------------------
        st.subheader("4️⃣ Generated Files")

        if not files:
            st.write("No files returned from API.")
        else:
            file_paths = [f["path"] for f in files]
            selected_path = st.selectbox(
                "Select a file to view its contents", file_paths
            )

            selected_file = next((f for f in files if f["path"] == selected_path), None)
            if selected_file:
                st.markdown(f"### `{selected_file['path']}`")

                # Guess language by extension for nicer highlighting
                ext = selected_file["path"].split(".")[-1].lower()
                lang_map = {
                    "py": "python",
                    "js": "javascript",
                    "ts": "typescript",
                    "html": "html",
                    "css": "css",
                    "json": "json",
                }
                lang = lang_map.get(ext, "")

                st.code(selected_file["content"], language=lang)

        # -----------------------
        #   DOWNLOAD ZIP
        # -----------------------
        st.subheader("5️⃣ Download Project")

        # Call /download-zip and offer a download button
        try:
            zip_bytes = call_download_zip()
            st.download_button(
                label="⬇️ Download project as ZIP",
                data=zip_bytes,
                file_name="generated_project_structured.zip",
                mime="application/zip",
            )
        except requests.RequestException as e:
            st.info(
                "No ZIP available yet or download failed. "
                "Generate a project first, then try again."
            )
            st.text(str(e))

        # -----------------------
        #   DOCKER / DEPLOYER
        # -----------------------
        deployer_result = data.get("deployer_result")
        if deployer_result:
            st.subheader("6️⃣ Docker Deployment")
            st.markdown(f"**Container name:** `{deployer_result.get('container_name', 'N/A')}`")
            st.markdown(f"**Port:** `{deployer_result.get('port', 'N/A')}`")
            st.markdown(f"**Containerized:** {'Yes' if deployer_result.get('containerized') else 'No (Dockerfile generated only)'}")

            if deployer_result.get("dockerfile_content"):
                with st.expander("View Dockerfile"):
                    st.code(deployer_result["dockerfile_content"], language="dockerfile")

            if deployer_result.get("docker_compose_content"):
                with st.expander("View docker-compose.yml"):
                    st.code(deployer_result["docker_compose_content"], language="yaml")

            col_status, col_stop, col_containerize = st.columns(3)
            with col_status:
                if st.button("📊 Check Container Status"):
                    try:
                        status = call_container_status_api()
                        st.json(status)
                    except requests.RequestException as e:
                        st.error(f"Failed: {e}")
            with col_stop:
                if st.button("🛑 Stop Container"):
                    try:
                        result = call_container_stop_api()
                        st.success(result.get("message", "Stopped"))
                    except requests.RequestException as e:
                        st.error(f"Failed: {e}")
        else:
            # Offer to containerize after the fact
            st.subheader("6️⃣ Docker Deployment")
            st.info("Project was generated without containerization.")
            if st.button("🐳 Containerize Now"):
                with st.spinner("Running Deployer agent..."):
                    try:
                        result = call_containerize_api()
                        st.success("Containerization complete!")

                        st.markdown(f"**Container name:** `{result.get('container_name', 'N/A')}`")
                        st.markdown(f"**Port:** `{result.get('port', 'N/A')}`")
                        st.markdown(f"**Containerized:** {'Yes' if result.get('containerized') else 'No (Dockerfile generated only)'}")

                        if result.get("dockerfile_content"):
                            with st.expander("View Dockerfile"):
                                st.code(result["dockerfile_content"], language="dockerfile")

                        if result.get("docker_compose_content"):
                            with st.expander("View docker-compose.yml"):
                                st.code(result["docker_compose_content"], language="yaml")

                        # Download updated ZIP (now includes Dockerfile + docker-compose.yml)
                        try:
                            zip_bytes = call_download_zip()
                            st.download_button(
                                label="⬇️ Download project with Docker files",
                                data=zip_bytes,
                                file_name="generated_project_structured.zip",
                                mime="application/zip",
                            )
                        except requests.RequestException:
                            st.warning("Could not prepare ZIP for download.")

                    except requests.RequestException as e:
                        st.error(f"Failed: {e}")

        # -----------------------
        #   RAW JSON (optional debug)
        # -----------------------
        with st.expander("🔍 Raw API response"):
            st.json(data)
    else:
        st.info("Generate a project to see the plan, tasks, files, and download link.")


if __name__ == "__main__":
    main()