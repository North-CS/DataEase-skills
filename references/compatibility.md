# Runtime and Agent compatibility

Compatibility has two independent layers:

1. The Skill package must be discoverable by the Agent and its `SKILL.md` loader.
2. The Agent runtime must be able to read local files, start Python/Node processes, reach DataEase over HTTP(S), and preserve the dry-run/apply arguments.

An Agent can understand the instructions without being able to execute the CLI. Do not label that case as full support.

## Operating systems

| Runtime host | Support level | Current evidence and limits |
|---|---|---|
| Windows 10/11 x64 | Verified | Unit/regression suite, CLI help, dependency installation, unpacked release smoke test, Playwright capture and live DataEase workflows were run from Windows. |
| Linux x86_64 | Designed support | Python, Node, `pathlib`, `sys.executable` and argument-list subprocess calls are portable. The target DataEase service and external dependency tests ran on CentOS, but the current release suite was not executed with Linux as the Skill host. Run the release checks before claiming Linux GA validation. |
| Linux arm64 | Compatible by dependency support | No architecture-specific code is used, but Python wheels, Node.js and Playwright Chromium must exist for the selected distribution and architecture. Not currently validated. |
| macOS Intel / Apple silicon | Designed support | The code avoids Windows-only APIs and shell syntax. Install a supported Python, Node.js and Playwright browser; use `DATAEASE_CA_BUNDLE` for private CAs. Not currently validated on physical macOS hardware. |

The DataEase server may run on a different operating system from the Skill host. Only network access to its HTTP(S) endpoint is required; SSH access is not part of normal operation.

Advanced API compatibility is a separate axis from host compatibility. `system adapter` supports source-inspected DataEase `2.7.x` through `2.10.25`, with per-family routing for visual detail, linkage, plugins and export. A future DataEase version may run on a verified Windows/Linux/macOS host yet still be mutation-blocked until its API/DTO behavior is validated.

## Runtime requirements

- Python 3.10 or newer for all API, safety, audit and planning workflows.
- `python -m pip install -r requirements.txt` for `requests`, `cryptography` and `PyJWT`.
- Node.js 18 or newer, npm, Playwright and Chromium only for screenshot/PDF capture.
- Local filesystem write access for plans, redacted snapshots, audit logs and artifacts.
- Network access to the configured DataEase URL and, when requested, the relevant identity, mail or enterprise platform endpoint.
- A UTF-8 capable terminal. The JSON result remains authoritative if a terminal font cannot render Chinese text.

Use the current interpreter instead of a hard-coded executable path. In documentation, `python` means the active virtual-environment interpreter; a Linux/macOS host may expose it as `python3`.

The capture engine uses Node Playwright only. Python Playwright is not a dependency and installing its Chromium creates a second, incompatible browser cache without helping this Skill. Run `system doctor` to check the installed Node package, Chromium executable and Linux shared libraries.

Always prefer a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
npm install
npx playwright install chromium
```

Do not make `--break-system-packages` the default installation path. On Debian/Ubuntu, missing browser libraries can be installed with `npx playwright install --with-deps chromium`. On RHEL/CentOS-family hosts, install the missing packages reported by `system doctor` with the system package manager; `libXdamage.so.1` is commonly provided by `libXdamage`.

## Agent support tiers

| Tier | Typical tools | How to use this Skill |
|---|---|---|
| Native or publicly documented Agent Skills support | OpenAI Codex, Claude Code, Cursor, Gemini CLI, GitHub Copilot, Qwen Code, Qoder and OpenClaw | Install the folder in that client's Skill location. The client reads `SKILL.md`; OpenAI-specific UI metadata in `agents/openai.yaml` may be ignored by other clients. Confirm the exact client/version documentation before distribution. |
| Manual Skill compatibility | Any coding Agent that can read the folder and run local commands | Point the Agent at `SKILL.md` and require it to invoke `scripts/dataease.py`. Automatic discovery, artifact rendering and permission prompts may differ. |
| Tool/API adapter required | Hosted chatbots or workflow Agents without a local filesystem/shell, including many SaaS deployments | Wrap the CLI as a controlled MCP tool, function call or internal service. Preserve stdout JSON, exit codes, plan storage, confirmation token input and secret isolation. |
| Unsupported execution | Agents that cannot reach DataEase, cannot persist a plan, or cannot pass exact arguments between dry-run and apply | They may explain the documentation but must not claim to perform mutations. |

This table is not a promise that every release of every listed client implements the same Skill schema. Agent Skills support is evolving; test discovery, command execution, plan persistence and artifact delivery in the intended client before calling it production-supported.

## Model capability compatibility

Multimodal understanding is optional. The authoritative creation path uses dataset metadata, deterministic semantic classification, fixed DTO adapters, smart-grid layout, theme luminance/contrast calculation, real chart-data calls and DOM counters. A model never needs to infer component coordinates, field IDs, colors or success from a screenshot.

| Model capability | Recommended workflow | Expected result |
|---|---|---|
| Text-only or smaller model | `visual autopilot --complexity compact` | Up to 6 components, deterministic theme/layout/interactions and machine-readable QA |
| Mainstream tool-using model | `visual autopilot --complexity standard` | Up to 10 components with richer chart diversity and detail preservation |
| Strong reasoning or multimodal model | `visual autopilot --complexity rich` or reviewed custom spec | Up to 16 components; visual inspection may guide optional aesthetic refinement |

Treat screenshots and SVG previews as optional presentation artifacts. Determine success from `quality.ready`, `quality.score`, `verification.chart_data_checks`, `query_capture`, publish status and capture render-state fields. A client that cannot display images can still return their paths and the DataEase preview URL.

`model_compatibility.multimodal_required=false` means the workflow is structurally complete without image understanding. It does not remove the runtime requirements for Python, network access, plan persistence or exact command execution.

## Host-specific output

- Codex: return absolute Markdown links or image paths.
- OpenClaw: use `MEDIA:<absolute_path>` when its host requires that protocol.
- Other clients: keep the DataEase preview URL and adapt the local artifact path to the client's attachment API.

Presentation differences must not change the CLI safety contract. L3 confirmation is enforced by `PlanStore` in Python, so an Agent cannot replace the confirmation token with a conversational claim that the user approved it.

## Porting checklist

Before marking a new OS/Agent combination as verified:

1. Validate Skill discovery and frontmatter parsing.
2. Create a fresh virtual environment and install Python dependencies.
3. Install npm dependencies and Playwright Chromium when capture is required.
4. Run all unit/regression tests and CLI help smoke tests.
5. Run `system doctor` and `system capabilities` against a disposable or authorized DataEase instance.
6. Verify one L1 dry-run/apply flow and one L3 wrong-token/correct-token flow.
7. Capture a dashboard/DataV and verify the client's artifact presentation.
8. Scan the installed Skill, plans, logs and artifacts for credentials.

Record the client name/version, operating system/architecture, Python, Node.js, DataEase version and test date in `validation.md`.

## Upstream references

- DataEase's original Skill uses the same `SKILL.md`, `scripts`, `references`, `templates` and `agents` layout: <https://github.com/dataease/DataEase-skills>.
- The Agent Skills format is an open, progressively loaded package model; implementation details can vary by client: <https://agentskills.io>.
- Current vendor/client support must be checked in each product's official documentation before release.
