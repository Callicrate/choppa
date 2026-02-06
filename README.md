# Choppa

> **Get to da cluster**

Run Python in Databricks straight from your laptop

[![PyPI version](https://badge.fury.io/py/choppa.svg)](https://badge.fury.io/py/choppa)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3291B6.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT+-BB8ED0.svg)](https://opensource.org/licenses/MIT)

## Because Running Code Shouldn't Be Hard

So you want to run something in Databricks? Strap in because they expect you to build jobs with their nifty homebrew orchestrator, deploy environments using [better-than-Terraform](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/bundles/direct) bundles, develop in their hosted [monaco UI](https://microsoft.github.io/monaco-editor/) (which is waaay better than whatever VSCode has), and, oh. Remote development? Like from your laptop? Did we mention their hosted notebooks already? They come with AI and _serverless_

You don't want to do any of that. You want to write some code and run it. Like a normal person.

## Installation

```bash
pip install choppa
```


## Configuration

Choppa will search and use the first cluster identifier it finds via:

- `DATABRICKS_CLUSTER_ID` environment variable
- If `DATABRICKS_CONFIG_PROFILE` environment variable is set then the `cluster_id` in `~/.databrickscfg` for that profile
- The `cluster_id` defined in `~/.databrickscfg`'s `DEFAULT` profile

You can also manually set the cluster whenever you want with 

```python
choppa.set_cluster(cluster_id="8675309")
```

## Quickstart

```python
import choppa

@choppa.remote
def add(a: int, b: int) -> int:
    return a + b

add(1, 2)  # 3
```

Donezo. You can probably stop reading now because that covers 99% of the frustration of Databricks development with _just a freaking decorator_

## Slowstart


### Scope

**Global variables** are handy but _don't work with Choppa_

**Do this**

```python
@choppa.remote
def some_math(a: int, exponent: int) -> int:
    return a ** exponent

some_math(2, 10) # 1024
```

**_Don't do this_**

```python
EXPONENT = 10

@choppa.remote
def some_math(a: int) -> int:
    return a ** EXPONENT

some_math(2)  # RemoteExecitionFailed: name 'EXPONENT' is not defined
```

### Context Managers

Normally each call to a `@choppa.remote` function uses its own execution context on your cluster. If that's confusing then just pretend I said 'process' instead, it's close enough. You can group work into a single process via a context manager

**Do this**

```python
@choppa.remote 
def some_math(a: int, b: int) -> int:
    return a + b

# 1 context
with choppa.session():
    x = [some_math(y, 1) for y in range(1_000)] 
```

**Don't do this**

```python
@choppa.remote 
def some_math(a: int, b: int) -> int:
    return a + b

# 1 bajillion contexts
x = [some_math(y, 1) for y in range(1_000)] 
```

## Requirements

- Python 3.10+
- `databricks-sdk` >= 0.20.0
- `cloudpickle` (for serializing arguments and results)

## License

MIT

---

Hey, boss, I just made literally every researcher's job easier, made them more productive, made them happier. Everyone who works for you and a significant chunk of data science people across the BU. I'm just talking out loud here but maybe _now_ I can get that promotion?

_(huh? what are 'people skills'...)_
