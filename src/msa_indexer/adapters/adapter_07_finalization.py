"""Stage 07: inspect finalization of a disposable one-file index run."""
from __future__ import annotations

from ._workbench_sandbox import index_capability, run_one_file


def finalization_capability(config) -> dict[str, bool | str | None]:
    return index_capability(config)


def preview_finalization(config, source, relative_path: str) -> dict:
    """Run the selected-file prerequisites and finalization in disposable SQLite."""
    return run_one_file(config, source, relative_path)
