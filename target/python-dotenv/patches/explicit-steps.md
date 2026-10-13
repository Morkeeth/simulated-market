## Getting Started

```shell
pip install python-dotenv
```

If your application takes its configuration from environment variables, like a
12-factor application, launching it in development is not very practical because
you have to set those environment variables yourself.

python-dotenv loads the configuration from a `.env` file when it is present
(e.g. in development) while remaining configurable via the environment.

Create a file named `.env` in the root directory of your project:

```bash
# .env
DOMAIN=example.org
ADMIN_EMAIL=admin@${DOMAIN}
ROOT_URL=${DOMAIN}/app
```

Create a file named `foo.py` next to it:

```python
# foo.py
import os

from dotenv import load_dotenv

load_dotenv()  # reads variables from a .env file and sets them in os.environ

print(os.getenv("DOMAIN"))
```

Run it:

```shell
python foo.py
```

It prints `example.org`. If it prints `None`, the `.env` file is not in the
same directory as `foo.py`.

By default, `load_dotenv()` will:

- Look for a `.env` file in the same directory as the Python script (or higher up the directory tree).
- Read each key-value pair and add it to `os.environ`.
- **Not override** existing environment variables (`override=False`). Pass `override=True` to override existing variables.

If you use variables in values, ensure they are surrounded with `{` and `}`,
like `${DOMAIN}`, as bare variables such as `$DOMAIN` are not expanded.

You will probably want to add `.env` to your `.gitignore`, especially if it
contains secrets like a password.
