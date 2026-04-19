# Extracting `cutiee-ace` and `cutiee-cu` into their own GitHub repos

> Renamed from `LIFT.md`. "Extract" reads better — these packages are
> already self-contained inside `packages/`; this guide just walks through
> moving each into its own GitHub repo with CI + PyPI publishing.

## Current state (what's already done)

Both packages live under `packages/` in this monorepo. Each is **fully
self-contained** — no cross-package imports, each ships its own copy of
the harness primitives (`Action`, `AgentState`, `ObservationStep`,
`env_utils`):

```
packages/
├── cutiee_ace/                     # ACE memory + pruning + harness
│   ├── pyproject.toml              # publishable: pip install cutiee-ace
│   ├── README.md                   # standalone usage docs
│   └── cutiee_ace/
│       ├── __init__.py             # public API (re-exports)
│       ├── harness/                # Action, AgentState, ObservationStep, env_utils
│       ├── memory/                 # ACE pipeline (12 modules)
│       ├── pruning/                # RecencyPruner + fg/bg + summarizer
│       └── safety/                 # risk_classifier + audit (used by reflector)
│
├── cutiee_cu/                      # Computer Use runner + browser + harness
│   ├── pyproject.toml              # publishable: pip install cutiee-cu
│   ├── README.md
│   └── cutiee_cu/
│       ├── __init__.py             # public API
│       ├── harness/                # Action, AgentState, ObservationStep, env_utils
│       ├── runner.py               # ComputerUseRunner
│       ├── browser/                # Playwright wrapper
│       ├── client/                 # GeminiComputerUseClient + MockComputerUseClient
│       └── safety/                 # ApprovalGate, audit, risk_classifier
│
└── EXTRACT.md                      # this file
```

Both packages have already passed end-to-end smoke tests:

```bash
$ python -c "from cutiee_ace import ACEMemory, RecencyPruner; ..."   # ✅
$ python -c "from cutiee_cu import ComputerUseRunner, ...; runner.run(...)"  # ✅
```

## Extraction procedure

### Step 1 — Create the GitHub repos

```bash
gh repo create cutiee-ace --public --description "Self-evolving ACE memory + temporal pruning for LLM agents"
gh repo create cutiee-cu  --public --description "Computer Use runner for LLM agents — Gemini ComputerUse + Playwright"
```

### Step 2 — Initialize each from the monorepo subdirectory

For `cutiee-ace`:

```bash
mkdir -p ~/work/cutiee-ace
cp -r packages/cutiee_ace/. ~/work/cutiee-ace/
cd ~/work/cutiee-ace
git init -b main
git remote add origin https://github.com/Edward-H26/cutiee-ace.git
git add .
git commit -m "Initial extract from CUTIEE monorepo"
git push -u origin main
```

Repeat for `cutiee-cu` (`packages/cutiee_cu/.` → `~/work/cutiee-cu/`).

### Step 3 — Add CI per package

Drop a `.github/workflows/test.yml` in each repo:

```yaml
name: test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[all]"
      - run: pip install pytest pytest-asyncio
      - run: pytest tests/ -v
```

(For `cutiee-cu` add `pip install playwright && playwright install chromium`
before the test step if you include browser-touching tests.)

### Step 4 — Migrate the relevant tests from the monorepo

```bash
# cutiee-ace — bring memory + pruner tests
cp CUTIEE/tests/agent/test_memory.py        ~/work/cutiee-ace/tests/
cp CUTIEE/tests/agent/test_pruner.py        ~/work/cutiee-ace/tests/
cp CUTIEE/tests/agent/test_state.py         ~/work/cutiee-ace/tests/
cp CUTIEE/tests/agent/test_safety.py        ~/work/cutiee-ace/tests/
# Bulk-rewrite imports: from agent.X → from cutiee_ace.X
find ~/work/cutiee-ace/tests -name "*.py" -exec sed -i '' 's/from agent\./from cutiee_ace./g' {} +

# cutiee-cu — bring runner + browser + CU model tests
cp CUTIEE/tests/agent/test_computer_use_runner.py    ~/work/cutiee-cu/tests/
cp CUTIEE/tests/agent/test_browser_env.py            ~/work/cutiee-cu/tests/
cp CUTIEE/tests/agent/test_cu_model_defaults.py      ~/work/cutiee-cu/tests/
cp CUTIEE/tests/agent/test_security.py               ~/work/cutiee-cu/tests/
cp CUTIEE/tests/agent/test_tier_semantics.py         ~/work/cutiee-cu/tests/
cp CUTIEE/tests/agent/test_state.py                  ~/work/cutiee-cu/tests/
cp CUTIEE/tests/agent/test_safety.py                 ~/work/cutiee-cu/tests/
find ~/work/cutiee-cu/tests -name "*.py" -exec sed -i '' 's/from agent\./from cutiee_cu./g' {} +
```

### Step 5 — Publish to PyPI

```bash
cd ~/work/cutiee-ace
pip install build twine
python -m build           # produces dist/cutiee_ace-0.1.0.{whl,tar.gz}
twine upload dist/*       # requires PyPI token in ~/.pypirc

cd ~/work/cutiee-cu
python -m build
twine upload dist/*
```

After publish:

```bash
$ pip install cutiee-ace cutiee-cu
$ python -c "from cutiee_ace import ACEMemory; from cutiee_cu import ComputerUseRunner"
```

### Step 6 — Add a docs site (mkdocs-material)

```bash
cd ~/work/cutiee-ace
pip install mkdocs-material
mkdocs new .
# Edit mkdocs.yml + docs/index.md (use README.md as the seed)
mkdocs gh-deploy
# Live at https://Edward-H26.github.io/cutiee-ace/
```

Same for `cutiee-cu`.

### Step 7 — (Optional) Keep the monorepo in sync

If you want CUTIEE to keep using the latest published versions instead
of vendored copies, switch the top-level `pyproject.toml` to depend on
the published packages:

```toml
dependencies = [
    "cutiee-ace>=0.1.0",
    "cutiee-cu>=0.1.0",
    # ... rest of CUTIEE deps (Django, Neo4j, etc.)
]
```

Then delete the `packages/` directory and the `agent/` directory's
relevant subpackages, replacing imports in `apps/` accordingly.

## What you get after extraction

- Two independently-versioned PyPI packages
- Each repo can move at its own pace (issues, releases, contributors)
- CUTIEE becomes a thin Django app on top of the two libraries
- Other projects can `pip install cutiee-ace` (or `cutiee-cu`) without
  pulling in CUTIEE's web stack

## Estimated effort

| Step | Time |
|---|---|
| 1 — Create GH repos | 5 min |
| 2 — Initial extract + push | 15 min |
| 3 — CI workflows | 30 min |
| 4 — Test migration + import rewrite | 30 min |
| 5 — PyPI publish | 30 min (incl. account setup) |
| 6 — Docs site | 60 min |
| 7 — Sync monorepo (optional) | 30 min |
| **Total** | **~3 hours per package, ~6 hours total** |

Less than the 1-2 days originally estimated because the heavy lifting
(actually separating the code, ensuring no cross-imports, writing the
public API) is already done in `packages/`.
