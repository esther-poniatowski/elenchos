# Contributing to "elenchos"

> [!IMPORTANT]
> To contribute effectively, please conform to those guidelines and use the provided templates.

## Submitting Issues

To submit a new issue:

1. In the repository page, navigate to the "Issues" tab and click on "New Issue".
2. Select and fill the issue template.
3. Add relevant labels, assignees, and milestone if applicable.

## Developing the Code

Contributions to the codebase should be developed in a local clone of the repository. Follow these
steps to set up a development environment:

### Installation

1. Initialize a local copy of the repository:

   ```sh
   cd /path/to/local/directory
   git clone git@github.com:esther-poniatowski/elenchos.git
   ```

2. Create a virtual environment containing the development dependencies:

   ```sh
   cd elenchos
   conda env create -f environment.yml
   ```

   By default, the environment will be named `elenchos`, as specified in the `environment.yml`
   file. This name can be modified by passing the `-n` option.

3. Register the package in "editable mode", from the root of the repository:

   ```sh
   conda activate elenchos
   pip install -e .
   ```

### Using the Commit Message Template

1. Edit the commit template (`.gitmessage`, at the root of the repository) to specify the name and
   email address of the committer.

2. Configure `git` to use this file as a commit template:

   ```sh
   git config commit.template .gitmessage
   ```

3. Verify the configuration:

   ```sh
   git config --get commit.template
   ```

### Commit Message Format

> [!NOTE]
> To write a commit message with this template, adhere to the following format:

- Capitalize the subject, do not add a period at the end
- Limit the subject line to 50 characters
- Use the imperative mood in the subject line
- Separate subject from body with a blank line
- Wrap the body at 72 characters per line
- Use the body to explain what and why (not how)
- Add references to issues or other commits using [GitHub keywords](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/using-keywords-in-issues-and-pull-requests)

## Writing Documentation

Every Markdown file under `docs/` is a note: it declares its metadata in a YAML frontmatter block, and it is registered in the index of the folder holding it. A file that satisfies neither is invisible to a reader navigating by index.

### Frontmatter Block

Three keys open every note, in this order:

```yaml
---
tags:
  - specification
index: "[Elenchos documentation](docs/_index.md)"
aliases:
  - Findings profile
---
```

- `tags` names the kind of the note, and its state when the note is not stable, drawn from the two vocabularies below. The kind comes first.
- `index` links the entry point of the folder holding the note, as a Markdown link whose path starts at the repository root. An `_index.md` points one level up instead, at the index of its parent folder; the documentation root has no parent and omits the key.
- `aliases` fixes the name under which the note is cited. Each alias is unique across `docs/`.

| Tag             | Kind of note                                               |
|-----------------|------------------------------------------------------------|
| `index`         | Folder entry point                                         |
| `specification` | Normative definition that producers and the gate implement |
| `migration`     | Mapping of existing outputs onto a specification           |
| `decision`      | Architecture decision record                               |

| Tag        | State of the note                             |
|------------|-----------------------------------------------|
| `wip`      | Note still being drafted                      |
| `revision` | Note under revision, whose content may change |

A stable note, or an accepted decision, carries no state tag.

A decision record adds three keys between `tags` and `index`, and states its state in `status` instead of a state tag:

- `status` places the decision in its life cycle: `proposed`, `accepted`, `deprecated` or `superseded`;
- `created` gives the date on which the record entered `docs/adr/`;
- `revised` gives the date of the last change to the decision or to its grounds.

### Registering a Note

Each folder carries an `_index.md` registering every file that it holds. Register a new file in the same edit that creates it.

An entry gives the title of the note as link text, followed by one clause stating why a reader opens the note. The clause opens on a verb in the present tense, whose implicit subject is the note, and it closes without a period.

### Cross-References

A cross-reference is a relative Markdown link carrying the `.md` extension. A finer reference appends a block anchor, declared at the end of the target line, such as `findings-profile.md#^ordinal`. Renaming a note, an anchor or an identifier requires updating every inbound reference in the same change.

### Source Entries

A note cites a work by a key of the form `authYYYY`, placed as a tail tag after the claim it supports. The "Sources" section of the note lists every cited key once, in alphabetical order:

```markdown
- [oasis2023] ◐ [OASIS, *Static Analysis Results Interchange Format (SARIF) Version 2.1.0 Plus Errata 01*, OASIS Standard, 2023](https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/sarif-v2.1.0-errata01-os-complete.pdf)
```

The mark after the key states how the entry was checked: ✓ the text was read in full · ◐ the entry was checked through an abstract, the publisher page, or a secondary summary · ○ the entry is cited from standard knowledge without a check. ^reading-marks

## Configuration File Organization

This project separates configuration concerns between two locations:

### `pyproject.toml` — Project Management

Contains only build system, package metadata, dependencies, entry points, and tool configurations
that **must** reside in `pyproject.toml` (because the tool does not support external config paths):

- `[build-system]` — Build backend (setuptools)
- `[project]` — Name, version, authors, license, description, keywords, classifiers, URLs
- `[project.dependencies]` — Runtime dependencies
- `[project.optional-dependencies]` — Optional dependency groups
- `[project.scripts]` — CLI entry points
- `[tool.setuptools]` — Package discovery and source layout
- `[tool.pytest.ini_options]` — Pytest settings (pytest does not support custom config paths)

### `config/tools/` — Tool-Specific Settings

Contains dedicated configuration files for each development tool. This achieves modular,
tool-specific settings that are decoupled from the main project file:

| File                  | Tool                   | Purpose                           |
|-----------------------|------------------------|-----------------------------------|
| `black.toml`          | Black                  | Code formatting rules             |
| `mypy.ini`            | MyPy                   | Static type checking rules        |
| `pylintrc.ini`        | Pylint                 | Linting rules (main code)         |
| `pylintrc_tests.ini`  | Pylint                 | Linting rules (test code)         |
| `pyrightconfig.json`  | Pyright                | Static type analysis overrides    |
| `releaserc.toml`      | Python Semantic Release| Versioning and release assets      |

### `config/dictionaries/` — Spell Checking

Custom word lists for CSpell (VS Code spell checker):

| File          | Contents                    |
|---------------|-----------------------------|
| `project.txt` | Project-specific terms      |
| `python.txt`  | Python language terms       |
| `tools.txt`   | Development tool names      |

### Rationale

- **Modularity**: Each tool's configuration is self-contained and independently editable.
- **Clarity**: `pyproject.toml` stays concise and focused on project identity.
- **Discoverability**: Tool configs are grouped in a single directory, easy to locate.
- **Flexibility**: Tools with complex configs (Pylint, MyPy) benefit from dedicated files
  with inline comments explaining each setting.
