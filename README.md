3d-resume

A JSON-powered single-page application (SPA) to display a technical engineer's resume along with interactive 3D STEP models for selected projects. The frontend is framework-driven (Preact) and uses three-cad-viewer (OpenCascade WebAssembly) to render .step/.stp files with zoom, rotate, fit, and reset controls.

Project highlights
- SPA and responsive layout (desktop and mobile)
- Data-driven from resume.json maintained by the author
- Uses a JS framework (Preact) to render project cards
- Interactive .STEP viewer per project with local file upload or remote URL
- Minimal Python dev server, packaged as a uv project named 3d-resume

Quick start (with uv)
1) Install uv if you haven’t:
   - curl -LsSf https://astral.sh/uv/install.sh | sh

2) Serve locally:
   - From this folder: uv run 3d-resume-serve
   - On first run, the server creates page/YYYYMMDD-HHMMSS.html from index.html and serves the newest page at http://localhost:PORT/index.html

3) Edit resume.json and refresh. The page re-fetches resume.json on reload.

Project structure
- index.html — SPA template shell, loads assets/js/app.js via ESM and preloads the viewer module
- assets/js/app.js — Loads resume.json, renders sections; Work section is built with Preact and wires three-cad-viewer
- assets/css/styles.css — Responsive styling
- resume.json — Source of truth for all resume data (author-maintained)
- src/three_d_resume/server.py — Dev server implementation (MIME for .js/.wasm/.step/.stp)
- main.py — Backward-compatibility shim that re-exports server API
- pyproject.toml — PEP 621 metadata, console script, setuptools config, uv dev-dependencies

Run tests
- Install uv (see above), then run:
  - uv run -m pytest
- uv will provision the dev dependency (pytest) from [tool.uv].

STEP models on projects
- To auto-load a model from the web, add a custom field to a work item in resume.json:
  "stepUrl": "https://example.com/path/to/model.step"  # .step or .stp URLs are supported
- An example local model is available in this repository under 3d-sources/step:
  "stepUrl": "./3d-sources/step/Spannvorrichtung.STEP"
- Or use the "Load .STEP" button on a project card to choose a local .step/.stp file.

STEP/IGES to JSON converter (optional)
- This repo includes a small Python CLI to convert STEP into the JSON format used by three-cad-viewer (see 3d-sources/test.json). It is optional and requires extra packages.
- Install the optional dependencies in your environment:
  - pip install ocp-tessellate build123d
  - or: pip install ocp-tessellate cadquery
- Convert:
  - uv run step-to-json --in path/to/model.step --out 3d-sources/model.json
  - Options: --name MyModel --color #ff0000 --deflection 0.1 --angle 12
- Then point a work item in resume.json to the JSON:
  "jsonUrl": "./3d-sources/model.json"

Notes
- three-cad-viewer downloads the OpenCascade WASM bundle at runtime; first load may take a few seconds.
- The viewer supports mouse/touch orbit, pan, and zoom. Use Fit View to frame the model, Reset to default.

License
MIT