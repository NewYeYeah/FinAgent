# Getting Started

This guide is the canonical environment and credential setup for FinAgent.

## 1. Requirements

- Python 3.11+
- Git
- Windows 10/11 x64 or Ubuntu 22.04/24.04
- Optional Conda/Miniconda

The repository CI currently validates Ubuntu Python 3.11/3.12/3.13 and Windows Python 3.11.

## 2. Clone and install

### Ubuntu

```bash
git clone https://github.com/NewYeYeah/FinAgent.git
cd FinAgent

conda env create -f environment/environment.yml
conda activate finagent
python -m pip install -e ".[dev]"
```

If the machine also has ROS 2 sourced into the shell, use the isolated wrapper:

```bash
./scripts/finagent.sh --check
./scripts/finagent.sh python -m pytest -q
```

### Windows PowerShell

```powershell
git clone https://github.com/NewYeYeah/FinAgent.git
Set-Location FinAgent

conda env create -f environment\environment.yml
conda activate finagent
python -m pip install -e ".[dev]"
```

Do not use `scripts/finagent.sh` or `scripts/run_tests.sh` from native PowerShell; they are Bash wrappers. Use `python -m pytest` directly.

## 3. Optional dependencies

Install only the surfaces required by the test or workflow:

```bash
python -m pip install -e ".[llm]"
python -m pip install -e ".[us-market]"
python -m pip install -e ".[cn-free]"
python -m pip install -e ".[a-share]"
python -m pip install -e ".[local-parquet]"
```

For a full research workstation:

```bash
python -m pip install -e ".[dev,llm,us-market,cn-free,a-share,local-parquet]"
```

## 4. Secret store

Tracked provider profiles never contain credentials. Copy the template outside the repository.

### Ubuntu

```bash
mkdir -p ~/.config/finagent
cp configs/secrets.example.toml ~/.config/finagent/secrets.toml
chmod 600 ~/.config/finagent/secrets.toml
```

### Windows PowerShell

```powershell
New-Item -ItemType Directory -Force "$HOME\.config\finagent" | Out-Null
Copy-Item configs\secrets.example.toml "$HOME\.config\finagent\secrets.toml"
notepad "$HOME\.config\finagent\secrets.toml"
```

Typical entries:

```toml
[api_keys]
deepseek_official = "..."
siliconflow = "..."
openai = "..."

[market_credentials.alpaca]
api_key = "..."
secret_key = "..."

[market_credentials.tushare]
token = "..."

[market_credentials.hithink]
api_key = "..."
```

Only configure providers that are actually used. `AKShare` requires no secret.

To use another secret file location:

```bash
export FINAGENT_SECRETS_FILE=/secure/path/secrets.toml
```

```powershell
$env:FINAGENT_SECRETS_FILE = "D:\secure\finagent\secrets.toml"
```

Never place credentials in tracked TOML files, Agent prompts, task metadata or reports.

## 5. Verify the environment

Ubuntu:

```bash
./scripts/finagent.sh python -m pytest -q
```

Windows:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
```

Check the package and timezone database:

```bash
python -c "import finagent; from zoneinfo import ZoneInfo; print(finagent.__file__); print(ZoneInfo('Asia/Shanghai')); print(ZoneInfo('America/New_York'))"
```

## 6. LLM connectivity smoke

```bash
python scripts/smoke_llm_provider.py configs/llm.toml --profile deepseek_official_v4_pro
```

A successful smoke only verifies provider connectivity and structured output. It does not validate Agent research quality.

## 7. Next steps

- Market data: `docs/guides/data-sources.md`
- Agent research: `docs/guides/agent-research.md`
- Tests: `docs/testing/testing.md`
