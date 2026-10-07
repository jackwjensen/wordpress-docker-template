"""Cases for the deploy-identity rules in standards_deploy.py.

The negatives carry most of the weight here. All three rules fire on a shape that was
universal across the estate on the day they were written, so their entire working life is
spent staying quiet on the corrected form -- a rule that flagged a SHA-pinned action, or a
multi-stage Dockerfile that drops root in its final stage, would be exempted wholesale
within a week, and an exempted rule is not running.

The dispatcher-reach cases at the bottom exist because of the `check_mojibake` incident
recorded in standards_checks.py: a rule can be correct, tested, and never called. "Run it
over all ten repos: zero findings" reads identically whether a rule is clean or blind.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from standards_core import CheckConfig
from standards_deploy import (
    check_container_user,
    check_deploy_host_key,
    check_deploy_ssh_user,
)
from standards_dispatch import check_source_file
from standards_scope import should_check
from standards_selftest import run_module_tests

WORKFLOW = Path(".github/workflows/deploy.yml")
DOCKERFILE = Path("Dockerfile")


def rules(violations) -> list[str]:
    return [violation.rule for violation in violations]


# ---- deploy-root-ssh -------------------------------------------------------------------

ROOT_STEP = (
    "      - name: Deploy via SSH",
    "        uses: appleboy/ssh-action@v1",
    "        with:",
    "          host: ${{ secrets.HETZNER_HOST }}",
    "          username: root",
    "          key: ${{ secrets.HETZNER_SSH_KEY }}",
    '          fingerprint: "SHA256:abc"',
)


def test_root_ssh_is_flagged() -> None:
    assert rules(check_deploy_ssh_user(WORKFLOW, list(ROOT_STEP))) == ["deploy-root-ssh"]


def test_root_ssh_is_flagged_when_quoted() -> None:
    lines = [line.replace("username: root", 'username: "root"') for line in ROOT_STEP]
    assert rules(check_deploy_ssh_user(WORKFLOW, lines)) == ["deploy-root-ssh"]


def test_root_ssh_is_flagged_as_a_template_default() -> None:
    """The shape wordpress-docker-template shipped: root as the value a clone inherits."""
    lines = [line.replace("username: root", "username: ${{ vars.DEPLOY_USER || 'root' }}") for line in ROOT_STEP]
    assert rules(check_deploy_ssh_user(WORKFLOW, lines)) == ["deploy-root-ssh"]


def test_a_named_deploy_user_passes() -> None:
    lines = [line.replace("username: root", "username: deploy") for line in ROOT_STEP]
    assert not list(check_deploy_ssh_user(WORKFLOW, lines))


def test_a_template_default_of_deploy_passes() -> None:
    lines = [line.replace("username: root", "username: ${{ vars.DEPLOY_USER || 'deploy' }}") for line in ROOT_STEP]
    assert not list(check_deploy_ssh_user(WORKFLOW, lines))


def test_username_outside_an_ssh_step_is_ignored() -> None:
    """`username` is an ordinary key elsewhere; only an SSH step hands out a shell."""
    lines = [
        "      - name: Start MySQL",
        "        with:",
        "          username: root",
    ]
    assert not list(check_deploy_ssh_user(WORKFLOW, lines))


def test_root_ssh_is_line_exemptable() -> None:
    lines = (
        list(ROOT_STEP[:4])
        + [
            "          # standards: deploy-root-ssh exempt -- single-tenant throwaway box that "
            "has no other account and is rebuilt from scratch on every run.",
            "          username: root",
        ]
        + list(ROOT_STEP[5:])
    )
    assert not list(check_deploy_ssh_user(WORKFLOW, lines))


# ---- deploy-no-hostkey ----------------------------------------------------------------


def test_missing_fingerprint_is_flagged() -> None:
    lines = [line for line in ROOT_STEP if "fingerprint" not in line]
    assert rules(check_deploy_host_key(WORKFLOW, lines)) == ["deploy-no-hostkey"]


def test_a_pinned_fingerprint_passes() -> None:
    assert not list(check_deploy_host_key(WORKFLOW, list(ROOT_STEP)))


def test_a_fingerprint_from_a_variable_passes() -> None:
    """The template's shape: the value is per-server, so it cannot be a literal."""
    lines = [
        line.replace('fingerprint: "SHA256:abc"', "fingerprint: ${{ vars.HOST_FINGERPRINT }}") for line in ROOT_STEP
    ]
    assert not list(check_deploy_host_key(WORKFLOW, lines))


def test_a_sha_pinned_action_still_parses() -> None:
    """A SHA pin is a stricter pin, not a different action. It must still be recognised."""
    lines = [
        line.replace(
            "appleboy/ssh-action@v1",
            "appleboy/ssh-action@0ff4204d59e8e51228ff73bce53f80d53301dee2  # v1",
        )
        for line in ROOT_STEP
        if "fingerprint" not in line
    ]
    assert rules(check_deploy_host_key(WORKFLOW, lines)) == ["deploy-no-hostkey"]


def test_a_later_steps_fingerprint_does_not_satisfy_an_earlier_one() -> None:
    """Two deploy targets in one workflow: pinning the second must not excuse the first."""
    lines = [
        "      - name: Deploy staging",
        "        uses: appleboy/ssh-action@v1",
        "        with:",
        "          username: deploy",
        "      - name: Deploy production",
        "        uses: appleboy/ssh-action@v1",
        "        with:",
        "          username: deploy",
        '          fingerprint: "SHA256:abc"',
    ]
    assert rules(check_deploy_host_key(WORKFLOW, lines)) == ["deploy-no-hostkey"]


def test_a_workflow_with_no_ssh_step_is_silent() -> None:
    assert not list(check_deploy_host_key(WORKFLOW, ["      - uses: actions/checkout@v5"]))


# ---- container-root-user ---------------------------------------------------------------


def test_a_dockerfile_with_no_user_is_flagged() -> None:
    lines = ["FROM mcr.microsoft.com/dotnet/aspnet:10.0", "WORKDIR /app", "COPY . ."]
    assert rules(check_container_user(DOCKERFILE, lines)) == ["container-root-user"]


def test_explicit_user_root_is_flagged_too() -> None:
    lines = ["FROM node:22", "USER root", 'CMD ["node", "server.js"]']
    assert rules(check_container_user(DOCKERFILE, lines)) == ["container-root-user"]


def test_app_uid_variable_passes() -> None:
    lines = ["FROM mcr.microsoft.com/dotnet/aspnet:10.0", "USER $APP_UID"]
    assert not list(check_container_user(DOCKERFILE, lines))


def test_named_user_passes() -> None:
    assert not list(check_container_user(DOCKERFILE, ["FROM node:22", "USER node"]))


def test_numeric_uid_passes() -> None:
    assert not list(check_container_user(DOCKERFILE, ["FROM alpine", "USER 1654"]))


def test_a_multi_stage_build_is_judged_on_its_final_stage() -> None:
    """The build stage needs root to install packages; it never ships."""
    lines = [
        "FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build",
        "USER root",
        "RUN dotnet publish -o /app/publish",
        "FROM mcr.microsoft.com/dotnet/aspnet:10.0",
        "COPY --from=build /app/publish .",
        "USER $APP_UID",
    ]
    assert not list(check_container_user(DOCKERFILE, lines))


def test_a_final_stage_that_returns_to_root_is_flagged() -> None:
    """Last USER wins, because that is what Docker does."""
    lines = ["FROM node:22", "USER node", "RUN something", "USER root"]
    assert rules(check_container_user(DOCKERFILE, lines)) == ["container-root-user"]


def test_a_stage_that_goes_to_root_and_drops_again_passes() -> None:
    lines = ["FROM node:22", "USER root", "RUN apt-get install -y fonts", "USER node"]
    assert not list(check_container_user(DOCKERFILE, lines))


def test_a_file_with_no_from_is_ignored() -> None:
    assert not list(check_container_user(DOCKERFILE, ["# just a comment"]))


def test_container_root_user_is_line_exemptable() -> None:
    lines = [
        "# standards: container-root-user exempt -- a build-tooling image that is never "
        "deployed and needs root to write into the mounted workspace.",
        "FROM alpine",
        "RUN apk add git",
    ]
    assert not list(check_container_user(DOCKERFILE, lines))


# ---- the rules are actually REACHED by the dispatcher ----------------------------------
#
# Not a formality. standards_checks.py records a rule that was correct, tested, and placed
# below an early return where it could never run, staying silent for weeks while its own
# verification reported "zero findings".


def dispatch(relative: str, body: str) -> list[str]:
    """Rule ids the REAL entry point yields, after confirming the file is even in scope."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        config = CheckConfig()
        assert should_check(target, root, config), f"{relative} is not in scope"
        lines = body.splitlines()
        return [violation.rule for violation in check_source_file(target, lines, config, {}, root)]


def test_dispatcher_reaches_the_workflow_rules() -> None:
    found = dispatch(
        ".github/workflows/deploy.yml",
        "jobs:\n"
        "  deploy:\n"
        "    needs: check\n"
        "    steps:\n"
        "      - uses: appleboy/ssh-action@v1\n"
        "        with:\n"
        "          username: root\n",
    )
    assert "deploy-root-ssh" in found
    assert "deploy-no-hostkey" in found


def test_dispatcher_reaches_the_dockerfile_rule() -> None:
    found = dispatch("Dockerfile", "FROM mcr.microsoft.com/dotnet/aspnet:10.0\nWORKDIR /app\n")
    assert "container-root-user" in found


def test_dispatcher_reaches_a_suffixed_dockerfile() -> None:
    found = dispatch("Dockerfile.worker", 'FROM python:3.12\nCMD ["python", "w.py"]\n')
    assert "container-root-user" in found


def test_a_compliant_dockerfile_produces_nothing() -> None:
    found = dispatch(
        "Dockerfile",
        "FROM mcr.microsoft.com/dotnet/aspnet:10.0\nWORKDIR /app\nUSER $APP_UID\n",
    )
    assert found == []


if __name__ == "__main__":
    sys.exit(run_module_tests(globals(), "deploy-identity cases"))
