# SCCS Fish -> Zsh Converter
#
# Walks a Fish shell config tree and emits an equivalent zsh profile tree.
# Unlike the PowerShell sibling, fish syntax is close enough to zsh that
# function bodies and control flow are translated best-effort instead of
# stubbed, and platform-specific files (*.macos.fish / *.linux.fish) are
# converted inside `uname` guards instead of being skipped.

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path

from sccs.convert.zsh_block import BlockTranslation, translate_block
from sccs.convert.zsh_templates import (
    CONFD_FILE_HEADER,
    CONVENIENCES_BLOCK,
    FUNCTION_FILE_HEADER,
    FUNCTION_STUB_HEADER,
    README_TEMPLATE,
    UNAME_GUARD_FOOTER,
    UNAME_GUARD_HEADER,
    ZSHRC_HEADER,
    ZSHRC_LOADER,
)
from sccs.utils.logging import get_logger
from sccs.utils.paths import atomic_write

logger = get_logger("sccs.convert")

# Default file patterns skipped when walking the source tree. Mirrors the
# PowerShell converter's list EXCEPT the platform-specific files
# (*.macos.fish / *.linux.fish), which are converted with a uname guard.
DEFAULT_ZSH_SKIP_PATTERNS: tuple[str, ...] = (
    # Fish runtime state — never useful as a converted profile.
    "fish_history",
    "fish_variables",
    # Conventional "local" override files are by convention machine-private.
    "*.local.fish",
    # SECURITY: any file the user marked as containing credentials/secrets.
    # These mirror the global_exclude patterns of SCCS itself, applied at
    # the conversion stage so secrets never make it into a `.zsh` artefact
    # that might end up in a sync repo.
    "*secret*",
    "*secrets*",
    "*token*",
    "*credential*",
    "*password*",
    "99-secrets.fish",
)

# Platform-suffix -> value reported by `uname` on that platform.
_PLATFORM_UNAME: dict[str, str] = {
    ".macos.fish": "Darwin",
    ".linux.fish": "Linux",
}


@lru_cache(maxsize=1)
def _find_zsh() -> str | None:
    return shutil.which("zsh")


def _zsh_syntax_ok(content: str) -> bool | None:
    """
    Validate generated content with `zsh -n` (parse only, no execution).

    The line-based translator cannot catch everything (e.g. fish multi-line
    command substitutions produce unbalanced parens) — this gate enforces
    the converter's hard promise to never ship syntactically broken zsh.
    Returns None when zsh is not installed (heuristics-only mode).
    """
    zsh = _find_zsh()
    if zsh is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, shell=False, parse-only
            [zsh, "-n"],
            input=content,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode == 0


@dataclass
class ZshConversionReport:
    """Summary of a Fish->Zsh conversion run."""

    files_processed: int = 0
    files_skipped: int = 0
    aliases_converted: int = 0
    env_vars_converted: int = 0
    path_lines_converted: int = 0
    functions_translated: int = 0
    functions_stubbed: int = 0
    lines_untranslated: int = 0
    fish_lines_passthrough: int = 0
    conveniences_emitted: bool = False
    warnings: list[str] = field(default_factory=list)
    written_files: list[Path] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)

    @property
    def total_converted(self) -> int:
        return self.aliases_converted + self.env_vars_converted + self.path_lines_converted


class FishToZshConverter:
    """
    Convert a Fish shell configuration directory into a zsh profile.

    Layout (input):  src_root/{config.fish, conf.d/*.fish, functions/*.fish}
    Layout (output): dst_root/{zshrc, conf.d/*.zsh, functions/*.zsh, README.md}
    """

    def __init__(
        self,
        src_root: Path,
        dst_root: Path,
        skip_patterns: tuple[str, ...] | None = None,
        *,
        include_conveniences: bool = True,
    ):
        self.src_root = src_root
        self.dst_root = dst_root
        self.skip_patterns = skip_patterns or DEFAULT_ZSH_SKIP_PATTERNS
        self.include_conveniences = include_conveniences

    # ------------------------------------------------------------------ public

    def convert_directory(self, *, dry_run: bool = False) -> ZshConversionReport:
        """
        Walk src_root and write a zsh profile under dst_root.

        With dry_run=True no files are written but the report still reflects
        what *would* be written (useful for previewing).
        """
        report = ZshConversionReport()

        if not self.src_root.exists():
            report.warnings.append(f"Source directory not found: {self.src_root}")
            return report

        # 1) conf.d/ — full best-effort translation (incl. platform guards)
        self._convert_confd(report, dry_run=dry_run)

        # 2) conf.d/95-conveniences.zsh — minimal extras zsh lacks natively.
        if self.include_conveniences:
            self._write_conveniences(report, dry_run=dry_run)

        # 3) functions/ — best-effort translation with stub fallback
        self._convert_functions(report, dry_run=dry_run)

        # 4) zshrc entry point
        self._write_zshrc_entry(report, dry_run=dry_run)

        # 5) README.md
        self._write_readme(report, dry_run=dry_run)

        return report

    # ---------------------------------------------------------------- internal

    def _convert_confd(self, report: ZshConversionReport, *, dry_run: bool) -> None:
        confd_src = self.src_root / "conf.d"
        confd_dst = self.dst_root / "conf.d"

        if not confd_src.is_dir():
            return

        for fish_file in sorted(confd_src.glob("*.fish")):
            if self._should_skip(fish_file):
                report.files_skipped += 1
                report.skipped_files.append(fish_file)
                continue

            zsh_file = confd_dst / (fish_file.stem + ".zsh")
            content = self._convert_confd_file(fish_file, report)
            if content is None:
                continue

            report.files_processed += 1
            self._write(zsh_file, content, dry_run=dry_run)
            report.written_files.append(zsh_file)

    def _write_conveniences(self, report: ZshConversionReport, *, dry_run: bool) -> None:
        """Write the comfort extras to conf.d/95-conveniences.zsh."""
        target = self.dst_root / "conf.d" / "95-conveniences.zsh"
        self._write(target, CONVENIENCES_BLOCK, dry_run=dry_run)
        report.conveniences_emitted = True
        report.written_files.append(target)

    def _convert_functions(self, report: ZshConversionReport, *, dry_run: bool) -> None:
        fn_src = self.src_root / "functions"
        fn_dst = self.dst_root / "functions"

        if not fn_src.is_dir():
            return

        for fish_file in sorted(fn_src.glob("*.fish")):
            if self._should_skip(fish_file):
                report.files_skipped += 1
                report.skipped_files.append(fish_file)
                continue

            zsh_file = fn_dst / (fish_file.stem + ".zsh")
            source_rel = fish_file.relative_to(self.src_root)

            lines = self._read_lines(fish_file)
            if lines is None:
                report.warnings.append(f"Cannot read {source_rel}")
                continue

            translation = translate_block(lines)
            report.files_processed += 1

            content = ""
            stub_reason: str | None = None
            if translation.should_stub:
                stub_reason = self._stub_reason(translation)
            else:
                header = FUNCTION_FILE_HEADER.format(
                    filename=fish_file.stem + ".zsh",
                    source_rel=source_rel,
                )
                content = header + "\n".join(translation.lines) + "\n"
                if _zsh_syntax_ok(content) is False:
                    stub_reason = "generated zsh failed `zsh -n` syntax check"

            if stub_reason is not None:
                content = self._stub_content(fish_file, stub_reason)
                report.functions_stubbed += 1
                report.warnings.append(f"Stubbed {source_rel}: {stub_reason}")
            else:
                report.functions_translated += 1
                self._merge_stats(report, translation)

            self._write(zsh_file, content, dry_run=dry_run)
            report.written_files.append(zsh_file)

    def _write_zshrc_entry(self, report: ZshConversionReport, *, dry_run: bool) -> None:
        target = self.dst_root / "zshrc"
        self._write(target, ZSHRC_HEADER + ZSHRC_LOADER, dry_run=dry_run)
        report.written_files.append(target)

    def _write_readme(self, report: ZshConversionReport, *, dry_run: bool) -> None:
        target = self.dst_root / "README.md"
        # Don't clobber an existing README.md — it may be hand-curated.
        if target.exists():
            return
        self._write(target, README_TEMPLATE, dry_run=dry_run)
        report.written_files.append(target)

    # ----------------------------------------------------------------- helpers

    def _should_skip(self, path: Path) -> bool:
        return any(fnmatch(path.name, pattern) for pattern in self.skip_patterns)

    @staticmethod
    def _read_lines(fish_file: Path) -> list[str] | None:
        try:
            return fish_file.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError) as exc:
            logger.warning("Cannot read %s: %s", fish_file, exc)
            return None

    @staticmethod
    def _uname_value(fish_file: Path) -> str | None:
        """Return the uname guard value for platform-specific files."""
        for suffix, uname_value in _PLATFORM_UNAME.items():
            if fish_file.name.endswith(suffix):
                return uname_value
        return None

    def _convert_confd_file(self, fish_file: Path, report: ZshConversionReport) -> str | None:
        source_rel = fish_file.relative_to(self.src_root)
        lines = self._read_lines(fish_file)
        if lines is None:
            report.warnings.append(f"Cannot read {source_rel}")
            return None

        translation = translate_block(lines)
        header = CONFD_FILE_HEADER.format(
            filename=fish_file.stem + ".zsh",
            source_rel=source_rel,
        )

        if translation.should_stub:
            # conf.d files are top-level statements; an unbalanced or overly
            # fish-specific file must not ship as live zsh either.
            reason = self._stub_reason(translation)
            report.warnings.append(f"Stubbed {source_rel}: {reason}")
            return self._stub_content(fish_file, reason)

        body_lines = translation.lines
        uname_value = self._uname_value(fish_file)
        if uname_value is not None:
            guarded = [UNAME_GUARD_HEADER.format(uname_value=uname_value)]
            guarded.extend(f"  {line}" if line else "" for line in body_lines)
            guarded.append(UNAME_GUARD_FOOTER)
            body_lines = guarded

        content = header + "\n".join(body_lines) + "\n"
        if _zsh_syntax_ok(content) is False:
            reason = "generated zsh failed `zsh -n` syntax check"
            report.warnings.append(f"Stubbed {source_rel}: {reason}")
            return self._stub_content(fish_file, reason)

        self._merge_stats(report, translation)
        return content

    @staticmethod
    def _stub_reason(translation: BlockTranslation) -> str:
        if translation.event_handler:
            return "fish event handler (--on-event/--on-variable)"
        if not translation.balanced:
            return "unbalanced block structure"
        return f"{translation.stats['untranslated']}/{translation.body_lines} lines untranslatable"

    def _stub_content(self, fish_file: Path, reason: str) -> str:
        source_rel = fish_file.relative_to(self.src_root)
        try:
            body = fish_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            return f"# Failed to read {source_rel}: {exc}\n"

        commented = "\n".join(f"# {line}" if line else "#" for line in body.splitlines())
        return (
            FUNCTION_STUB_HEADER.format(
                filename=fish_file.stem + ".zsh",
                source_rel=source_rel,
                reason=reason,
            )
            + "\n"
            + commented
            + "\n"
        )

    @staticmethod
    def _merge_stats(report: ZshConversionReport, translation: BlockTranslation) -> None:
        report.aliases_converted += translation.stats["alias"]
        report.env_vars_converted += translation.stats["env"]
        report.path_lines_converted += translation.stats["path"]
        report.lines_untranslated += translation.stats["untranslated"]
        report.fish_lines_passthrough += translation.stats["passthrough"]
        report.warnings.extend(translation.warnings)

    def _write(self, target: Path, content: str, *, dry_run: bool) -> None:
        if dry_run:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        # Backup any pre-existing file so the user can recover hand edits.
        # Atomic + 0600: shell profiles can carry exported secrets, and a
        # crash mid-backup must not leave a truncated .bak behind.
        if target.exists():
            backup = target.with_suffix(target.suffix + ".bak")
            atomic_write(backup, target.read_text(encoding="utf-8"), mode=0o600)
        target.write_text(content, encoding="utf-8")
