# SCCS Fish -> PowerShell Converter
#
# Walks a Fish shell config tree and emits an equivalent PowerShell profile
# tree. Aliases, environment variables, and PATH manipulations are converted
# directly; everything else (especially Fish function bodies) is preserved as
# a commented stub for hand-porting.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sccs.convert.rules import convert_line
from sccs.convert.templates import (
    CONFD_FILE_HEADER,
    FUNCTION_STUB_HEADER,
    PROFILE_HEADER,
    PROFILE_LOADER,
    README_TEMPLATE,
)
from sccs.utils.logging import get_logger

logger = get_logger("sccs.convert")

# Default file patterns we skip outright when walking the source tree.
# `.macos.fish` / `.linux.fish` files are platform-specific and not relevant
# on Windows. History/state files must never be exported.
DEFAULT_SKIP_PATTERNS: tuple[str, ...] = (
    # Platform-specific files belong on their respective OS only.
    "*.macos.fish",
    "*.linux.fish",
    # Fish runtime state — never useful as a converted profile.
    "fish_history",
    "fish_variables",
    # Conventional "local" override files are by convention machine-private.
    "*.local.fish",
    # SECURITY: any file the user marked as containing credentials/secrets.
    # These mirror the global_exclude patterns of SCCS itself, applied at
    # the conversion stage so secrets never make it into a `.ps1` artefact
    # that might end up in a sync repo.
    "*secret*",
    "*secrets*",
    "*token*",
    "*credential*",
    "*password*",
    "99-secrets.fish",
)

# Fish keywords that mark a function body as non-trivial — used purely for
# diagnostics so the user sees roughly what the stub contains.
NON_TRIVIAL_KEYWORDS: tuple[str, ...] = (
    " for ",
    " while ",
    " switch ",
    " case ",
    " if ",
    " else",
    " begin",
    "string ",
    "command -q",
    "$argv[",
)


@dataclass
class ConversionReport:
    """Summary of a Fish->PowerShell conversion run."""

    files_processed: int = 0
    files_skipped: int = 0
    aliases_converted: int = 0
    functions_wrapped: int = 0  # alias-with-args → PS function
    env_vars_converted: int = 0
    path_lines_converted: int = 0
    functions_stubbed: int = 0
    fish_lines_passthrough: int = 0
    warnings: list[str] = field(default_factory=list)
    written_files: list[Path] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)

    @property
    def total_converted(self) -> int:
        return self.aliases_converted + self.functions_wrapped + self.env_vars_converted + self.path_lines_converted


class FishToPwshConverter:
    """
    Convert a Fish shell configuration directory into a PowerShell profile.

    Layout (input):  src_root/{config.fish, conf.d/*.fish, functions/*.fish}
    Layout (output): dst_root/{Microsoft.PowerShell_profile.ps1,
                                conf.d/*.ps1, functions/*.ps1, README.md}
    """

    def __init__(
        self,
        src_root: Path,
        dst_root: Path,
        skip_patterns: tuple[str, ...] | None = None,
    ):
        self.src_root = src_root
        self.dst_root = dst_root
        self.skip_patterns = skip_patterns or DEFAULT_SKIP_PATTERNS

    # ------------------------------------------------------------------ public

    def convert_directory(self, *, dry_run: bool = False) -> ConversionReport:
        """
        Walk src_root and write a PowerShell profile under dst_root.

        With dry_run=True no files are written but the report still reflects
        what *would* be written (useful for previewing).
        """
        report = ConversionReport()

        if not self.src_root.exists():
            report.warnings.append(f"Source directory not found: {self.src_root}")
            return report

        # 1) conf.d/ — alias / env / path conversion
        self._convert_confd(report, dry_run=dry_run)

        # 2) functions/ — emit stubs
        self._convert_functions(report, dry_run=dry_run)

        # 3) Profile entry point
        self._write_profile_entry(report, dry_run=dry_run)

        # 4) README.md
        self._write_readme(report, dry_run=dry_run)

        return report

    # ---------------------------------------------------------------- internal

    def _convert_confd(self, report: ConversionReport, *, dry_run: bool) -> None:
        confd_src = self.src_root / "conf.d"
        confd_dst = self.dst_root / "conf.d"

        if not confd_src.is_dir():
            return

        for fish_file in sorted(confd_src.glob("*.fish")):
            if self._should_skip(fish_file):
                report.files_skipped += 1
                report.skipped_files.append(fish_file)
                continue

            ps_file = confd_dst / (fish_file.stem + ".ps1")
            content, stats = self._convert_fish_file(fish_file)

            report.files_processed += 1
            report.aliases_converted += stats["alias"]
            report.functions_wrapped += stats["function"]
            report.env_vars_converted += stats["env"]
            report.path_lines_converted += stats["path"]
            report.fish_lines_passthrough += stats["passthrough"]

            self._write(ps_file, content, dry_run=dry_run)
            report.written_files.append(ps_file)

    def _convert_functions(self, report: ConversionReport, *, dry_run: bool) -> None:
        fn_src = self.src_root / "functions"
        fn_dst = self.dst_root / "functions"

        if not fn_src.is_dir():
            return

        for fish_file in sorted(fn_src.glob("*.fish")):
            if self._should_skip(fish_file):
                report.files_skipped += 1
                report.skipped_files.append(fish_file)
                continue

            ps_file = fn_dst / (fish_file.stem + ".ps1")
            content = self._stub_function_file(fish_file)
            report.files_processed += 1
            report.functions_stubbed += 1
            self._write(ps_file, content, dry_run=dry_run)
            report.written_files.append(ps_file)

    def _write_profile_entry(self, report: ConversionReport, *, dry_run: bool) -> None:
        target = self.dst_root / "Microsoft.PowerShell_profile.ps1"
        content = PROFILE_HEADER + PROFILE_LOADER
        self._write(target, content, dry_run=dry_run)
        report.written_files.append(target)

    def _write_readme(self, report: ConversionReport, *, dry_run: bool) -> None:
        target = self.dst_root / "README.md"
        # Don't clobber an existing README.md — it may be hand-curated.
        if target.exists():
            return
        self._write(target, README_TEMPLATE, dry_run=dry_run)
        report.written_files.append(target)

    # ----------------------------------------------------------------- helpers

    def _should_skip(self, path: Path) -> bool:
        from fnmatch import fnmatch

        return any(fnmatch(path.name, pattern) for pattern in self.skip_patterns)

    def _convert_fish_file(self, fish_file: Path) -> tuple[str, dict[str, int]]:
        """
        Convert a fish conf.d file to PowerShell.

        Returns (content, stats) where stats is a dict of conversion counters.
        """
        source_rel = fish_file.relative_to(self.src_root)
        ps_lines: list[str] = [
            CONFD_FILE_HEADER.format(
                filename=fish_file.stem + ".ps1",
                source_rel=source_rel,
            )
        ]

        stats = {"alias": 0, "function": 0, "env": 0, "path": 0, "passthrough": 0}

        try:
            text = fish_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            logger.warning("Cannot read %s: %s", fish_file, exc)
            ps_lines.append(f"# WARN: failed to read source: {exc}")
            return "\n".join(ps_lines) + "\n", stats

        in_function = False

        for raw_line in text.splitlines():
            stripped = raw_line.strip()

            # Preserve blank lines and comments verbatim.
            if not stripped:
                ps_lines.append("")
                continue
            if stripped.startswith("#"):
                ps_lines.append(raw_line)
                continue

            # Skip fish function bodies inside conf.d files — they're rare but
            # appear (e.g. inline `function fishplugin_...; ...; end`).
            if stripped.startswith("function "):
                in_function = True
                ps_lines.append(f"# fish-original (function block): {stripped}")
                stats["passthrough"] += 1
                continue
            if in_function:
                if stripped == "end":
                    in_function = False
                ps_lines.append(f"# fish-original: {stripped}")
                stats["passthrough"] += 1
                continue

            # Run the conversion pipeline.
            result = convert_line(raw_line)
            if result is None:
                ps_lines.append(f"# fish-original: {stripped}")
                stats["passthrough"] += 1
                continue

            if result.kind == "alias":
                stats["alias"] += 1
            elif result.kind == "function":
                stats["function"] += 1
            elif result.kind == "env":
                stats["env"] += 1
            elif result.kind == "path":
                stats["path"] += 1

            ps_lines.append(result.powershell)

        return "\n".join(ps_lines) + "\n", stats

    def _stub_function_file(self, fish_file: Path) -> str:
        source_rel = fish_file.relative_to(self.src_root)
        try:
            body = fish_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            return f"# Failed to read {source_rel}: {exc}\n"

        commented = "\n".join(f"# {line}" if line else "#" for line in body.splitlines())
        non_trivial = any(kw in body for kw in NON_TRIVIAL_KEYWORDS)
        marker = "complex" if non_trivial else "simple"

        return (
            FUNCTION_STUB_HEADER.format(
                filename=fish_file.stem + ".ps1",
                source_rel=source_rel,
            )
            + f"# Complexity hint: {marker}\n\n"
            + commented
            + "\n"
        )

    def _write(self, target: Path, content: str, *, dry_run: bool) -> None:
        if dry_run:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        # Backup any pre-existing file so the user can recover hand edits.
        if target.exists():
            backup = target.with_suffix(target.suffix + ".bak")
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        target.write_text(content, encoding="utf-8")
