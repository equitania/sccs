# SCCS Default Configuration
# Full default configuration as Python dict and YAML generator

from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "repository": {
        "path": "~/gitbase/sccs-sync",
        "remote": "origin",
        "auto_commit": False,
        "auto_push": False,
        "auto_pull": False,
        "commit_prefix": "[SYNC]",
    },
    "sync_categories": {
        # Claude Framework
        "claude_framework": {
            "enabled": True,
            "description": "SuperClaude Framework files (CLAUDE.md, PERSONAS.md, etc.)",
            "local_path": "~/.claude",
            "repo_path": ".claude/framework",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "include": [
                "CLAUDE.md",
                "COMMANDS.md",
                "FLAGS.md",
                "MCP.md",
                "MODES.md",
                "ORCHESTRATOR.md",
                "PERSONAS.md",
                "PRINCIPLES.md",
                "RULES.md",
            ],
            "exclude": [],
        },
        # Claude Skills
        "claude_skills": {
            "enabled": True,
            "description": "Claude Code Skills - directories with SKILL.md",
            "local_path": "~/.claude/skills",
            "repo_path": ".claude/skills",
            "sync_mode": "bidirectional",
            "item_type": "directory",
            "item_marker": "SKILL.md",
            "include": ["*"],
            "exclude": ["_archive/*", "_deprecated/*", "*.tmp"],
        },
        # Claude Commands
        "claude_commands": {
            "enabled": True,
            "description": "Claude Code Commands - single .md files",
            "local_path": "~/.claude/commands",
            "repo_path": ".claude/commands",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "item_pattern": "*.md",
            "include": ["*"],
            "exclude": ["_*.md", "*.local.md"],
        },
        # Claude Hooks
        "claude_hooks": {
            "enabled": True,
            "description": "Claude Code Hooks - Pre/Post Event Handler",
            "local_path": "~/.claude/hooks",
            "repo_path": ".claude/hooks",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "include": ["*.sh", "*.py", "*.js", "hook.json", "hooks.json"],
            "exclude": ["*.local.*", "_*.sh"],
        },
        # Claude Scripts
        "claude_scripts": {
            "enabled": True,
            "description": "Claude Code Utility Scripts",
            "local_path": "~/.claude/scripts",
            "repo_path": ".claude/scripts",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "include": ["*.sh", "*.py", "*.fish"],
            "exclude": ["_*.sh"],
        },
        # Claude Plugins
        "claude_plugins": {
            "enabled": True,
            "description": "Claude Code Plugin configurations",
            "local_path": "~/.claude/plugins",
            "repo_path": ".claude/plugins",
            "sync_mode": "local_to_repo",
            "item_type": "file",
            "include": ["config.json", "enabled.json"],
            "exclude": ["cache/*", "*.lock"],
        },
        # Claude Plans (disabled by default)
        "claude_plans": {
            "enabled": False,
            "description": "Claude Code Session Plans",
            "local_path": "~/.claude/plans",
            "repo_path": ".claude/plans",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "item_pattern": "*.md",
            "include": ["*.md"],
            "exclude": ["*.tmp", "*-draft.md"],
        },
        # Claude TODOs (disabled by default)
        "claude_todos": {
            "enabled": False,
            "description": "Claude Code persistent TODO lists",
            "local_path": "~/.claude/todos",
            "repo_path": ".claude/todos",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "include": ["*.json", "*.md"],
            "exclude": ["*.session.*"],
        },
        # Claude MCP Configs
        "claude_mcp": {
            "enabled": True,
            "description": "MCP Server Configurations",
            "local_path": "~/.claude/mcp",
            "repo_path": ".claude/mcp",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "include": ["*.json", "*.yaml", "*.yml"],
            "exclude": ["*.local.*", "credentials.*"],
        },
        # Claude Statusline
        "claude_statusline": {
            "enabled": True,
            "description": "Claude Code Statusline Script",
            "local_path": "~/.claude",
            "repo_path": ".claude/statusline",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "item_pattern": "statusline.*",
            "include": ["statusline.sh", "statusline.py", "statusline.fish"],
            "exclude": [],
        },
        # Fish Shell Configuration
        "fish_config": {
            "enabled": True,
            "description": "Fish Shell Configuration",
            "local_path": "~/.config/fish",
            "repo_path": ".config/fish",
            "sync_mode": "bidirectional",
            "item_type": "mixed",
            "include": [
                "config.fish",
                "README.md",
                "functions/*.fish",
                "conf.d/*.fish",
                "completions/*.fish",
            ],
            "exclude": [
                "fish_history",
                "fish_variables",
                "*.local.fish",
                "conf.d/*local*.fish",
                "conf.d/*secret*.fish",
                "*.macos.fish",
            ],
        },
        # Fish Shell macOS Config (conf.d/*.macos.fish)
        "fish_config_macos": {
            "enabled": True,
            "description": "Fish Shell macOS-specific Configuration",
            "local_path": "~/.config/fish/conf.d",
            "repo_path": ".config/fish/conf.d",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "item_pattern": "*.macos.fish",
            "include": ["*.macos.fish"],
            "exclude": [],
            "platforms": ["macos"],
        },
        # Fish Functions (separate category)
        "fish_functions": {
            "enabled": True,
            "description": "Fish Shell Custom Functions",
            "local_path": "~/.config/fish/functions",
            "repo_path": ".config/fish/functions",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "item_pattern": "*.fish",
            "include": ["*.fish"],
            "exclude": ["_*.fish", "*.local.fish", "macos/*"],
        },
        # Fish Functions macOS (functions/macos/*.fish)
        "fish_functions_macos": {
            "enabled": True,
            "description": "Fish Shell macOS-specific Functions",
            "local_path": "~/.config/fish/functions/macos",
            "repo_path": ".config/fish/functions/macos",
            "sync_mode": "bidirectional",
            "item_type": "file",
            "item_pattern": "*.fish",
            "include": ["*.fish"],
            "exclude": [],
            "platforms": ["macos"],
        },
        # Starship Prompt
        "starship_config": {
            "enabled": True,
            "description": "Starship Prompt Configuration",
            "local_path": "~/.config/starship.toml",
            "repo_path": ".config/starship.toml",
            "sync_mode": "bidirectional",
            "item_type": "file",
        },
        # Git Config (disabled by default)
        "git_config": {
            "enabled": False,
            "description": "Git Configuration (without credentials)",
            "local_path": "~/.gitconfig",
            "repo_path": ".config/git/gitconfig",
            "sync_mode": "bidirectional",
            "item_type": "file",
        },
        # Project Templates (disabled by default)
        "project_templates": {
            "enabled": False,
            "description": "Project templates for new projects",
            "local_path": "~/.config/project-templates",
            "repo_path": ".config/project-templates",
            "sync_mode": "bidirectional",
            "item_type": "directory",
            "include": ["*"],
            "exclude": [".git", "node_modules", "__pycache__"],
        },
    },
    "global_exclude": [
        # System files
        ".DS_Store",
        "*.swp",
        "*.swo",
        "*~",
        ".git",
        "__pycache__",
        "*.pyc",
        # Local/private files
        ".env",
        ".env.*",
        "*.local",
        "*.local.*",
        # SECURITY: Sensitive files - NEVER sync these!
        "*token*",
        "*secret*",
        "*credential*",
        "*password*",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*_rsa",
        "*_ed25519",
        "*_ecdsa",
        "*_dsa",
        "id_rsa*",
        "id_ed25519*",
        "known_hosts",
        ".pypirc",
        ".npmrc",
        ".netrc",
        "fish_variables",
        "*.keychain*",
        "*oauth*",
        "*auth*.json",
        "*.gpg",
    ],
    "path_transforms": {
        "placeholders": {
            "HOME": "{{HOME}}",
            "USER": "{{USER}}",
            "HOSTNAME": "{{HOSTNAME}}",
            "CLAUDE_DIR": "{{CLAUDE_DIR}}",
            "WORKSPACE": "{{WORKSPACE}}",
        },
        "transform_files": [
            {"pattern": "settings.template.json", "source": "settings.json"},
        ],
    },
    "conflict_resolution": {
        "default": "prompt",
        "per_category": {
            "claude_framework": "repo",
            "claude_skills": "prompt",
            "fish_config": "local",
        },
    },
    "output": {
        "verbose": False,
        "colored": True,
        "log_file": "~/.config/sccs/sync.log",
        "sync_history": "~/.config/sccs/history.yaml",
    },
}


def generate_default_config() -> str:
    """Generate default configuration as YAML string with comments."""
    header = """# SCCS - SkillsCommandsConfigsSync Configuration
# Version: 2.0
#
# This file configures synchronization between local files and a git repository.
# Each sync_category can be individually enabled/disabled.
#
# Sync modes:
#   - bidirectional: Two-way sync (changes flow both directions)
#   - local_to_repo: Only export local changes to repository
#   - repo_to_local: Only import repository changes locally
#
# Item types:
#   - file: Individual files
#   - directory: Directories (identified by item_marker)
#   - mixed: Both files and directories

"""
    return header + yaml.dump(DEFAULT_CONFIG, default_flow_style=False, sort_keys=False, allow_unicode=True)


def get_minimal_config(repo_path: str = "~/gitbase/sccs-sync") -> dict[str, Any]:
    """Get minimal configuration with only essential categories enabled."""
    config = DEFAULT_CONFIG.copy()
    config["repository"] = {**config["repository"], "path": repo_path}

    # Disable optional categories
    for category in ["claude_plans", "claude_todos", "git_config", "project_templates"]:
        if category in config["sync_categories"]:
            config["sync_categories"][category]["enabled"] = False

    return config
