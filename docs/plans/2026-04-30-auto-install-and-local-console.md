# Marneo auto install + local console convergence plan

## Goal

Add an automatic installation path so new users do not need to manually clone the repo, install editable Python package, then discover setup commands one by one.

This should work together with the proposed local web console:

- `curl | bash` or one copied command installs Marneo.
- `marneo setup` configures Provider and creates first employee.
- User can choose local-only/browser usage or Feishu usage.
- Local-only users can run `marneo web` without configuring Feishu.
- Feishu users can continue into `marneo setup feishu` and `marneo gateway start`.

## Current context

Repo: `/Users/chamber/code/marneo-agent`

Current installation state:

- `pyproject.toml` already defines package metadata and CLI entrypoint:
  - `[project].name = "marneo"`
  - `requires-python = ">=3.11"`
  - `[project.scripts] marneo = "marneo.cli.app:app"`
- README currently documents manual development-style install only:
  - `git clone git@github.com:ChamberZ40/marneo-agent.git`
  - `python3 -m pip install -e .`
- No install shell script found.
- No Makefile found.
- Deploy spec exists but is incomplete/stale in `openspec/changes/deploy-production/`.
- `marneo gateway install-service` exists in `marneo/cli/gateway_cmd.py`, but it expects deploy files that may not exist in the repo/package.
- Existing gateway daemon writes:
  - `~/.marneo/gateway.pid`
  - `~/.marneo/gateway.log`
- Existing config/data location:
  - `~/.marneo/config.yaml`
  - `~/.marneo/employees/`
  - `~/.marneo/projects/`

## Product decision

Yes, we need automatic installation.

Without it, the GitHub README looks developer-oriented, not product-oriented. A normal user should see one command and get to either:

```text
marneo web
```

or:

```text
marneo setup feishu
marneo gateway start
```

## Recommended install strategy

### Tier 1: pipx install from GitHub

Primary install command:

```bash
pipx install git+https://github.com/ChamberZ40/marneo-agent.git
```

Why:

- Isolated virtualenv.
- Exposes `marneo` on PATH.
- Does not pollute system Python.
- Better than `pip install --user` for CLI tools.

### Tier 2: one-line installer script

Add:

```text
scripts/install.sh
```

Then README can show:

```bash
curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash
```

The script should:

1. Detect OS: macOS / Linux / WSL.
2. Check Python >= 3.11.
3. Check/install guidance for `pipx`.
4. Run `pipx install git+https://github.com/ChamberZ40/marneo-agent.git` or `pipx upgrade marneo` if already installed.
5. Verify `marneo --version`.
6. Print next steps:
   - `marneo setup`
   - `marneo hire`
   - `marneo web` for local-only
   - `marneo setup feishu` for Feishu

Important: The script should not silently install Homebrew or system packages without confirmation. It should print exact commands when prerequisites are missing.

### Tier 3: development install remains documented

Keep developer path:

```bash
git clone git@github.com:ChamberZ40/marneo-agent.git
cd marneo-agent
python3 -m pip install -e '.[dev]'
python3 -m pytest tests -q
```

But move it below user install.

## Installation UX

README top quickstart should become:

```bash
# 1. Install
curl -fsSL https://raw.githubusercontent.com/ChamberZ40/marneo-agent/main/scripts/install.sh | bash

# 2. Configure Provider
marneo setup

# 3. Create your first digital employee
marneo hire

# 4A. Local-only usage
marneo web

# 4B. Feishu usage
marneo setup feishu
marneo gateway start
```

After `marneo setup`, product flow should ask:

```text
你想如何使用 Marneo？
1. 本地浏览器使用（推荐新手）：marneo web
2. 飞书中使用：marneo setup feishu
3. 两者都要
```

## Files likely to change

### Add install script

```text
scripts/install.sh
```

Responsibilities:

- portable bash
- `set -euo pipefail`
- version checks
- pipx install/upgrade
- PATH guidance
- no secret logging

### Add local doctor command

```text
marneo/cli/doctor_cmd.py
marneo/cli/app.py
```

Command:

```bash
marneo doctor
```

Checks:

- Python version
- Marneo version
- config path and whether Provider configured
- employee count
- Feishu config count
- gateway pid/status
- gateway health endpoint
- data directory permissions
- optional web console status later

This is key for installer verification and user support.

### Improve service install packaging

Current `marneo gateway install-service` depends on:

```text
deploy/com.marneo.gateway.plist
deploy/marneo-gateway.service
```

Need to verify/add those files and include them in package data.

Add/change:

```text
deploy/com.marneo.gateway.plist
deploy/marneo-gateway.service
pyproject.toml
```

If files are packaged, avoid using `Path(__file__).parent.parent.parent / "deploy"` in installed pipx environments unless verified. Better use `importlib.resources` or generate service templates dynamically.

### README update

Update install section:

- one-line install
- pipx direct install
- developer install
- local-only flow
- Feishu flow
- troubleshooting PATH/pipx/Python 3.11

### Tests

Add:

```text
tests/test_install_script.py
tests/cli/test_doctor_cmd.py
```

Test install script via static checks:

- file exists and executable
- contains `set -euo pipefail`
- checks Python >= 3.11
- does not contain real secrets
- has `pipx install` / `pipx upgrade`

Doctor tests:

- no config case
- provider configured case
- no employees case
- gateway pid stale case

## Implementation phases

### Phase 1: User install path

Deliverables:

- `scripts/install.sh`
- README quickstart update
- package metadata sanity check
- tests for script content

Verification:

```bash
bash -n scripts/install.sh
python3 -m pytest tests -q
```

Optional manual dry run:

```bash
MARNEO_INSTALL_DRY_RUN=1 bash scripts/install.sh
```

### Phase 2: Doctor command

Deliverables:

- `marneo doctor`
- secret-safe status output
- README troubleshooting section references doctor

Verification:

```bash
python3 -m marneo.cli.app doctor
python3 -m pytest tests -q
```

### Phase 3: Service install hardening

Deliverables:

- service templates included or generated
- `marneo gateway install-service` works after pipx install
- macOS launchd path and Linux user systemd path verified

Verification:

```bash
python3 -m marneo.cli.app gateway install-service --help
python3 -m pytest tests -q
```

Do not actually install system service in CI tests; unit-test generated paths/templates.

### Phase 4: Local console integration

After web console exists:

- installer prints `marneo web` as the local-only next step
- `marneo doctor` checks web console status
- README shows local-only path before Feishu path

## Security constraints

1. Installer must never ask for or print Provider key / Feishu secret.
2. Setup handles secrets after install, not shell script.
3. No `sudo` by default.
4. No automatic Homebrew install without user confirmation.
5. README must warn users to inspect install script if using `curl | bash`.
6. `doctor` must redact all secrets and env values.

## Open questions

1. Do we plan to publish to PyPI as `marneo`?
   - If yes, final user command can become `pipx install marneo`.
   - Until then, GitHub URL install is enough.

2. Do we want Homebrew formula later?
   - Good for macOS product feel.
   - Not necessary for MVP.

3. Do we want a desktop app later?
   - Local web console + installer is enough for now.
   - Desktop packaging can come after UX stabilizes.

## Recommendation

Implement automatic install before building too much frontend.

Priority order should be:

1. `scripts/install.sh` + README install flow
2. `marneo doctor`
3. local web console backend MVP
4. local web frontend
5. service install hardening

This gives us a complete product funnel:

```text
install -> setup -> hire -> local web or Feishu -> doctor/support
```
