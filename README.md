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

### Caching

Consider this straightforward workflow

```python
from databricks.connect import DatabricksSession

spark = DatabricksSession.builder.getOrCreate()

def get_stuff() -> list[Row]:
    return spark.table("huge_table").limit(1_000_000_000).collect()

def analyze_stuff(rows: list[Row]):
    return len(rows)

data = get_stuff()
result = analyze_stuff(data)
```

I bet you're having fun downloading those _billion_ rows from Databricks! Haven't even gotten to your analysis yet and you're already wishing computers came with hardware...

You'd maybe get to your `analysis()` sooner if you could cache the result on Databricks and only pass a _reference_ over the network

```python
from choppa import Choppa

choppa = Choppa(
    artifact_dir="/Workspace/Users/you@company/artifacts",
    max_result_size=2**10
)

@choppa.remote
def get_stuff() -> list[Row]:
    return spark.table("huge_table").limit(1_000_000_000).collect()

def analyze_stuff(rows: list[Row]):
    return len(rows)


ref = get_stuff() # type: ArtifactRef
```

Since a literal billion rows will blow through 1K bytes the result isn't returned. But then you have this `ArtifactRef` thing and need `analyze_stuff()` to use your actual `data`. Your could always materialize the artifact and run your analysis locally

```python
data = ref.dereference() # hahaha, that's right- it's C all over again. sucker!
result = analyze_stuff(data)
```

Yeah, it's a cute trick but doesn't have a lot of value since you still need to download `data` eventually. Hmm.... I know! You could let Choppa automagically deal with `ArtifactRef`s behind the scenes (it does), run everything on Databricks (you should), and just run your code (the freakin' dream)

```python
from choppa import Choppa

choppa = Choppa(
    artifact_dir="/Workspace/Users/you@company/artifacts",
    result_size_max=2**10
)

@choppa.remote
def get_stuff() -> list[Row]:
    return spark.table("huge_table").limit(1_000_000_000).collect()

@choppa.remote
def analyze_stuff(rows: list[Row]):
    return len(rows)

data = get_stuff()
result = analyze_stuff(data)
```

> There are actually 2 decorators you can use if you want to be a bit more certain with what is returned as a reference
>
> - **choppa.artifact** will **always** cache results, returning an `ArtifactRef` object
> - **choppa.remote** will **opportunistically** return your data but fall back to an `ArtifactRef` if the serialized value is larger > than `result_size_max`. If you don't set `result_size_max` or set it to `None` then `choppa.remote` will **always** return your data

### Context Managers

There's not a ton of savings to be had but you can use a context manager to group remote calls together. This does **not** invalidate the stuff I said about variables not being in-scope. What you get is faster execution because the remote process is reused for multiple function calls. You could probably get cute and create globals inside remote functions and have them persist in memory without having to write to disk or be sent over the network.. That's actually a pretty good idea. I'll think about it for version 2. Anyway, here's an example

```python
from choppa import Choppa

dutch = Choppa()

@dutch.remote
def some_math(a: int, b: int) -> int:
    return a + b

with dutch.session():
    x = [some_math(y,1) for y in range(1_000)]

```

### Async / Fire-and-Forget

And because my wife loves the idea of me turning off my laptop on occasion, maybe you just want to yeet a hard job at Databricks and walk away for a while. Easy peasy

```python
from choppa import Choppa

dutch = Choppa()

@dutch.submit
def slow_job():
    # ... hours of processing ...
    return results

# Returns immediately
handle = slow_job() # type: RemoteHandle

# Later...
ref = handle.wait()
data = dutch.dereference(ref)

# or another option
while not handle.done():
    pass
ref = handle.get_pointer() # type: ArtifactRef
data = dutch.dereference(ref)
```

## Requirements

- Python 3.10+
- `databricks-sdk` >= 0.20.0
- Authenticated workspace (env vars, profile, or Azure CLI)

## License

MIT

---

Hey, boss, I just made literally every researcher's job easier, made them more productive, made them happier. Every IC who works for you and a significant chunk of data science people across the BU. I'm just talking out loud here but maybe _now_ I can get that promotion?

(huh? what are 'people skills'...)
