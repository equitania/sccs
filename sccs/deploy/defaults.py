# The four bundled deployment profiles.
#
# Skill names are verified against ~/.claude/skills as of 01.09.2026. A
# profile naming a skill that no longer exists is caught by
# `sccs deploy show`, which reports it rather than shipping a gap.

from __future__ import annotations

from sccs.deploy.schema import DeploymentProfile

# Framework files every knowledge-bearing profile carries. Without
# CLAUDE.md/RULES.md the agent on the customer host does not behave like
# ours (fish syntax, delete protection, commit prefixes). They are never
# under `retain` — SOUL.md is our working method.
_FRAMEWORK = ["CLAUDE.md", "SOUL.md", "PRINCIPLES.md", "RULES.md"]

_SHELL = {
    "fish_config": ["*"],
    "fish_functions": ["*"],
    "starship_config": ["*"],
}
_SHELL_RETAIN = ["fish_config", "fish_functions", "starship_config"]

DEFAULT_DEPLOYMENT_PROFILES: dict[str, DeploymentProfile] = {
    "odoo-server": DeploymentProfile(
        description="Odoo work on a customer server",
        target_platform="linux",
        include={
            "claude_skills": [
                "odoo-common",
                "odoo16",
                "odoo17",
                "odoo18",
                "odoo19",
                "odoo-shell",
                "odoo-dev",
                "odoorpc-toolbox",
                "odoo-module-migrator",
                "odoo-merge-to",
                "myodoo-docker",
                "docker-expert",
                "nginx-set-conf",
                "uv-python-tools",
                "sharp-edges",
                "verification-loop",
                "session-hygiene",
            ],
            "claude_commands": ["s.md", "docs.md", "finalize.md", "tips.md"],
            "claude_agents": ["odoo-developer.md", "python-toolsmith.md"],
            "claude_framework": _FRAMEWORK,
            **_SHELL,
        },
        retain=list(_SHELL_RETAIN),
    ),
    "odoo-dev-full": DeploymentProfile(
        description="Full Odoo development incl. documentation and publication",
        target_platform="linux",
        extends="odoo-server",
        include={
            "claude_skills": [
                "odoo-module-docs",
                "odoo-funktionsumfang",
                "odoo-funktionsumfang-merge",
                "eq-helper-docs",
                "odoo-appstore-listing",
                "odoo-module2website",
                "odoo-website-design",
                "odoo-website-themes",
                "odoo-docs-sync",
                "odoo-agent-doc-coverage",
                "odoo-ai-addon",
                "odoo-chat",
                "eq-chatbot-core",
                "ownerp-demodata",
                "odoo-differ",
                "odoo-migration-estimator",
                "clean-room",
                "changelog-automation",
                "project-docs",
                "create-test-plan",
                "tdd-workflow",
                "glab",
                "gitlab-workflow",
            ],
            "claude_commands": ["afterwork.md", "check-skills.md", "project-audit.md"],
        },
    ),
    "fastreport": DeploymentProfile(
        description="FastReport work on a customer server",
        target_platform="linux",
        include={
            "claude_skills": [
                "fr-reports",
                "fr-mapper",
                "fr-odoo",
                "fr-api",
                "fr-designer",
                "odoo-common",
                "uv-python-tools",
            ],
            "claude_commands": ["s.md", "docs.md", "finalize.md"],
            "claude_agents": ["fastreport-integrator.md", "odoo-developer.md"],
            "claude_framework": _FRAMEWORK,
            **_SHELL,
        },
        retain=list(_SHELL_RETAIN),
    ),
    "shell-only": DeploymentProfile(
        description="Environment only — no knowledge, nothing to revoke",
        target_platform="linux",
        include={
            **_SHELL,
            "git_config": ["*"],
            "project_templates": ["*"],
        },
        retain=[*_SHELL_RETAIN, "git_config", "project_templates"],
    ),
}
