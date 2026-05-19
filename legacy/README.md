# Legacy Files

This directory stores code and design-template files that are not used by the
current Tauri/FastAPI Orchestra runtime.

Current runtime path:

- `ux/` Tauri desktop app
- `run_local_api.py` FastAPI sidecar
- `app_services.py`, `run_worker.py`, `workflow_engine.py`
- `local_dashboard_runner.py` agent stage execution helpers

Archived groups:

- `python_entrypoints/`: older CLI, Streamlit, and Discord-owned workflow entrypoints.
- `ux_unused/`: Figma/shadcn template files that are not imported by the current app.

Discord support files in the project root are intentionally kept because the
project may still advertise Discord support through the FastAPI-backed Discord
adapter.
