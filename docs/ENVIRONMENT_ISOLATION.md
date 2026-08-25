# FinAgent Environment Isolation Guide

## Why isolation is required

FinAgent is a standard Python quantitative research package. It is not a ROS2 package and must not inherit ROS2 Python plugins.

A contaminated shell may contain:

```text
/opt/ros/jazzy/lib/python3.12/site-packages

ament pytest plugins
launch_testing_ros
```

These plugins can be discovered by pytest before FinAgent tests start and may cause collection failures.

## Recommended workflow

Use a dedicated terminal:

```bash
conda activate finagent
```

Do not run:

```bash
source /opt/ros/jazzy/setup.bash
```

in the same shell before testing.

## Verify shell contamination

```bash
echo $PYTHONPATH
echo $AMENT_PREFIX_PATH
python -c "import sys; print(sys.executable)"
```

Expected:

```text
.../miniconda3/envs/finagent/bin/python
```

## Canonical test command

Use:

```bash
./scripts/run_tests.sh
```

or:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
```

The launcher disables third-party pytest plugin discovery and guarantees that tests use only FinAgent dependencies.
