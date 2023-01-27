# Windows EXE Support

The scraper can be built as a self-contained Windows EXE that does not require installing Python or pip dependencies.

This is a quick documentation for the developers.

## Building

To build, a Windows machine (or VM) is required. PyInstaller cannot cross-compile.

**Python 3.10.1 is required.** There is a bug with the `dis` module in 3.10.0 that prevents successful build.

1. Clone the repository and install the dependencies using `poetry install` (don't specify `--no-dev`).
2. Ensure reproducible builds by doing `set PYTHONHASHSEED=1`.
3. Run `poetry run pyinstaller pyinstaller.spec`, if it works, the EXE will be in `dist`.

The version number is embedded in the file name and inside the file as metadata.
It can be changed by changing the `major`, `minor` and `patch` variables inside `pyinstaller.spec` before building.

## Development

There are some considerations to take when writing code that may run in the Python interpreter or as a PyInstaller executable.

To determine if running as a regular Python script or as an EXE, check `sys.frozen` using `getattr`:

```python
is_exe = getattr(sys, "frozen", False)
```

When running as an EXE, be mindful of directories.

The path to the original EXE that was executed is in `sys.executable`, so all "user-facing" directories like `__user_data__`, `__settings__`, etc, should be relative to `os.path.dirname(sys.executable)`.

The path to the temporary extracted Python files and other data files is in `sys._MEIPASS`, needed to load resources like database scripts and others.

PyInstaller will try to include everything referenced automatically, but some things must be told manually in `pyinstaller.spec` - for now some support files for the `useragent` module and the SQLAlchemy database scripts.

Any logic to load a resource should try to determine the directory like this:

```python
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    directory = sys._MEIPASS
else:
    directory = os.path.dirname(__file__)
```

In the script, the current directory (`os.getcwd()`) is kept at the user-facing directory - relative paths will not load resources properly in the EXE case.

Also, `exit()` is not defined in PyInstaller, use `sys.exit()` instead, or import it:

```python
from sys import exit
```
