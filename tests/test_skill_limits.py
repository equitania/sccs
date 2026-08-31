"""Source-side SKILL.md limit checks (sccs/integrations/skill_limits.py).

The class of bug these guard: both the Pi and the Codex export copy skills
verbatim, so a source violating the shared agentskills.io limits is copied
faithfully and then silently dropped by the target. The export reports success
while the skill never loads.
"""

from __future__ import annotations

from sccs.integrations.skill_limits import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    check_skill_file,
    check_skill_text,
    scan_claude_skills,
)


def _skill(description: str = "does a thing", name: str = "my-skill") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n"


def _write_skill(root, name: str, text: str):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d


class TestCheckSkillText:
    def test_acceptable_skill_has_no_problems(self):
        assert check_skill_text(_skill()) == []

    def test_description_at_the_limit_is_accepted(self):
        assert check_skill_text(_skill("d" * MAX_DESCRIPTION_LENGTH)) == []

    def test_one_character_over_the_limit_is_reported(self):
        problems = check_skill_text(_skill("d" * (MAX_DESCRIPTION_LENGTH + 1)))
        assert len(problems) == 1
        # The measured value is named so the reader need not count characters.
        assert str(MAX_DESCRIPTION_LENGTH + 1) in problems[0]
        assert str(MAX_DESCRIPTION_LENGTH) in problems[0]

    def test_folded_scalar_description_is_measured_after_folding(self):
        """A >- block is how an over-long description hides: the source lines
        are short, only the folded value breaks the limit."""
        long_value = ("word " * 300).strip()
        text = "---\nname: s\ndescription: >-\n  " + long_value + "\n---\n\nBody.\n"
        problems = check_skill_text(text)
        assert problems and "description is" in problems[0]

    def test_over_long_name_is_reported(self):
        problems = check_skill_text(_skill(name="n" * (MAX_NAME_LENGTH + 1)))
        assert any(f"limit is {MAX_NAME_LENGTH}" in p for p in problems)

    def test_missing_description_is_reported(self):
        assert check_skill_text("---\nname: s\n---\n\nBody.\n") == [
            "frontmatter has no 'description' — the target cannot load this skill"
        ]

    def test_unparsable_frontmatter_names_the_cause(self):
        # Two flow sequences on one line: Claude Code's documented argument-hint
        # syntax, and invalid YAML.
        text = "---\nname: s\nargument-hint: [a] [b]\ndescription: d\n---\n\nBody.\n"
        problems = check_skill_text(text)
        assert len(problems) == 1
        assert "not valid YAML" in problems[0]

    def test_missing_frontmatter_block_is_reported(self):
        assert check_skill_text("Just a body.\n") == ["no frontmatter block — the target cannot load this skill"]

    def test_non_mapping_frontmatter_is_not_a_yaml_error(self):
        """`---\\n# heading\\n---` is a Markdown horizontal rule, not a broken
        skill: it must be reported as missing frontmatter, never as bad YAML."""
        problems = check_skill_text("---\n# heading\n---\n\nBody.\n")
        assert problems == ["no frontmatter block — the target cannot load this skill"]


class TestCheckSkillFile:
    def test_reads_from_disk(self, tmp_path):
        skill = _write_skill(tmp_path, "s", _skill("d" * 2000))
        assert check_skill_file(skill / "SKILL.md")

    def test_unreadable_file_is_reported_not_raised(self, tmp_path):
        problems = check_skill_file(tmp_path / "nope" / "SKILL.md")
        assert len(problems) == 1
        assert "could not read" in problems[0]


class TestScanClaudeSkills:
    def test_only_offenders_are_listed(self, tmp_path):
        _write_skill(tmp_path, "good", _skill())
        _write_skill(tmp_path, "bad", _skill("d" * 2000))

        violations = scan_claude_skills(tmp_path)
        assert list(violations) == ["bad"]

    def test_missing_directory_is_empty_not_an_error(self, tmp_path):
        assert scan_claude_skills(tmp_path / "absent") == {}

    def test_exclude_patterns_are_honoured(self, tmp_path):
        _write_skill(tmp_path, "gsd-thing", _skill("d" * 2000))
        assert scan_claude_skills(tmp_path, exclude_patterns=["gsd-*"]) == {}

    def test_private_and_dot_directories_are_skipped(self, tmp_path):
        _write_skill(tmp_path, "_draft", _skill("d" * 2000))
        _write_skill(tmp_path, ".hidden", _skill("d" * 2000))
        assert scan_claude_skills(tmp_path) == {}

    def test_directory_without_skill_md_is_ignored(self, tmp_path):
        (tmp_path / "notaskill").mkdir()
        assert scan_claude_skills(tmp_path) == {}
