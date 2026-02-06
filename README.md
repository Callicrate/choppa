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

Choppa needs to know what cluster to run stuff on. In-order of precedence, Choppa will use the cluster:

- set via the `cluster_id` parameter when you instanciate `Choppa`
- whatever you put in the environment variable `DATABRICKS_CLUSTER_ID`
- the value of `cluster_id` in `~/.databrickscfg`
  - if the environment variable `DATABRICKS_CONFIG_PROFILE` is set, using that profile
  - otherwise using the `DEFAULT` profile

## Usage

```python
from choppa import Choppa

dutch = Choppa()

@dutch.remote
def add(a: int, b: int) -> int:
    return a + b

add(1, 2)  # 3
```

Donezo. You can probably stop reading now because that covers 99% of the frustration of Databricks development with _just a freaking decorator_

## Advanced Usage

### Scope

Choppa only instantiates remote environments for contexts that are possible to scope without having to `inspect` frames or mess with function ASTs. Or, put another way: **Only functions and arguments are in-scope**.

```python
from choppa import Choppa

EXPONENT = 10

dutch = Choppa()

# This version works but is pretty boring
@dutch.remote
def an_option(a: int, exponent: int) -> int:
    return a ** exponent

# This one uses ONE WEIRD TRICK to always produce the exact same result!
@dutch.remote
def another_option(a: int) -> int:
    return a ** EXPONENT
```

### Context Managers

There's not a ton of savings to be had but you can use a context manager to group remote calls together. This does **not** invalidate the stuff I said about variables not being in-scope. What you get is faster execution because the remote process is reused for multiple function calls.

```python
from choppa import Choppa

dutch = Choppa()

@dutch.remote
def some_math(a: int, b: int) -> int:
    return a + b

with dutch.session():
    x = [some_math(y, 1) for y in range(1_000)]
```

## Requirements

- Python 3.10+
- `databricks-sdk` >= 0.20.0
- `cloudpickle` (for serializing arguments and results)
- Authenticated workspace (env vars, profile, or Azure CLI)

## License

MIT

---

Hey, boss, I just made literally every researcher's job easier, made them more productive, made them happier. Everyone who works for you and a significant chunk of data science people across the BU. I'm just talking out loud here but maybe _now_ I can get that promotion?

_(huh? what are 'people skills'...)_
