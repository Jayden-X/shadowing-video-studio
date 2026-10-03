import asyncio
import json
import os
import platform
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from shadowing_video_studio.provider_settings import ProviderSettings
from shadowing_video_studio.providers.process import SubprocessRunner, check_codex_event
from shadowing_video_studio.text_processing import (
    MAX_OUTPUT_BYTES,
    PreparationError,
    ProviderAvailability,
    parse_proposal,
    segmentation_prompt,
    segmentation_schema,
)

# Availability requires support for every control; older CLIs do not weaken isolation.
DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "hooks",
    "multi_agent",
    "remote_plugin",
    "plugins",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "view_image",
    "sleep_tool",
    "skill_search",
    "skill_mcp_dependency_install",
    "code_mode",
    "code_mode_host",
    "goals",
    "memories",
    "shell_snapshot",
    "daemon_auto_start",
)
REQUIRED_FLAGS = (
    "--ignore-user-config",
    "--ignore-rules",
    "--ephemeral",
    "--output-schema",
    "--output-last-message",
    "--skip-git-repo-check",
    "--strict-config",
    "--json",
)
SAFE_ENVIRONMENT = {
    "PATH",
    "PATHEXT",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TMP",
    "TEMP",
    "TMPDIR",
    "CODEX_HOME",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
}


def codex_environment(environment: Mapping[str, str]) -> dict[str, str]:
    # Do not forward DeepSeek/OpenAI API keys or unrelated application secrets.
    return {key: value for key, value in environment.items() if key.upper() in SAFE_ENVIRONMENT}


def resolve_executable(configured: str) -> list[str]:
    executable = shutil.which(configured) if configured else None
    if not executable:
        raise PreparationError(
            "Install Codex CLI or configure CODEX_EXECUTABLE on the backend.", 503
        )
    path = Path(executable).resolve()
    if path.suffix.lower() == ".cmd":
        # Recognize npm's known layout instead of interpreting the batch wrapper with a shell.
        script = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        package = script.parent.parent
        architecture = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
        triple = "aarch64-pc-windows-msvc" if architecture == "arm64" else "x86_64-pc-windows-msvc"
        roots = (
            package / "vendor",
            package / "node_modules" / "@openai" / f"codex-win32-{architecture}" / "vendor",
            path.parent / "node_modules" / "@openai" / f"codex-win32-{architecture}" / "vendor",
        )
        for root in roots:
            for directory in ("bin", "codex"):
                native = root / triple / directory / "codex.exe"
                if script.is_file() and native.is_file():
                    return [str(native)]
        node = path.parent / "node.exe"
        node_path = str(node) if node.is_file() else shutil.which("node")
        if not script.is_file() or not node_path:
            raise PreparationError(
                "Use a native Codex executable or its standard npm installation.", 503
            )
        return [node_path, str(script)]
    if path.suffix.lower() in {".bat", ".ps1"}:
        raise PreparationError(
            "Configure a native Codex executable; shell wrappers are unsupported.", 503
        )
    return [str(path)]


def disabled_feature_arguments() -> list[str]:
    return [part for feature in DISABLED_FEATURES for part in ("--disable", feature)] + [
        "--enable",
        "skip_host_skill_discovery",
    ]


def parse_features(content: bytes) -> dict[str, bool]:
    try:
        values = {}
        for line in content.decode("utf-8").splitlines():
            match = re.fullmatch(r"(\w+)\s+.+?\s+(true|false)", line.strip())
            if match:
                values[match[1]] = match[2] == "true"
        if not all(
            feature in values for feature in (*DISABLED_FEATURES, "skip_host_skill_discovery")
        ):
            raise ValueError
        return values
    except (ValueError, UnicodeError) as exc:
        raise PreparationError(
            "Update Codex CLI: required isolation controls are unavailable.", 503
        ) from exc


def parse_servers(content: bytes) -> dict[str, bool]:
    try:
        items = json.loads(content)
        if not isinstance(items, list):
            raise ValueError
        servers = {}
        for item in items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not item["name"]
                or len(item["name"]) > 200
                or not isinstance(item.get("enabled"), bool)
                or item["name"] in servers
            ):
                raise ValueError
            servers[item["name"]] = item["enabled"]
        return servers
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise PreparationError(
            "Codex MCP isolation could not be verified. Check the CLI configuration.", 503
        ) from exc


class CodexTextProvider:
    def __init__(self, settings: ProviderSettings, runner: SubprocessRunner | None = None) -> None:
        self._settings = settings
        self._runner = runner or SubprocessRunner()

    async def _probe(self, command: list[str], cwd: Path, env: dict[str, str]) -> list[str]:
        async def run(arguments: list[str], include_stderr: bool = False) -> bytes:
            result = await self._runner.run(arguments, cwd=cwd, environment=env, timeout=10)
            if result.returncode:
                raise PreparationError(
                    "Codex readiness checks failed. Check login and configuration.", 503
                )
            return result.stdout + result.stderr if include_stderr else result.stdout

        help_text = (await run([*command, "exec", "--help"])).decode("utf-8")
        if any(flag not in help_text for flag in REQUIRED_FLAGS):
            raise PreparationError(
                "Update Codex CLI: required isolation flags are unavailable.", 503
            )
        controls = disabled_feature_arguments()
        features = parse_features(await run([*command, *controls, "features", "list"]))
        if (
            any(features[feature] for feature in DISABLED_FEATURES)
            or not features["skip_host_skill_discovery"]
        ):
            raise PreparationError(
                "Codex keeps tools enabled. Update its CLI or managed configuration.", 503
            )
        # List inspects configuration, never starts MCP servers. Do not retain its raw data.
        servers = parse_servers(await run([*command, *controls, "mcp", "list", "--json"]))
        mcp_controls = [
            part
            for name in servers
            for part in ("-c", f"mcp_servers.{json.dumps(name)}.enabled=false")
        ]
        verified = parse_servers(
            await run([*command, *controls, *mcp_controls, "mcp", "list", "--json"])
        )
        if any(verified.values()) or set(verified) != set(servers):
            raise PreparationError("Inherited Codex MCP servers could not be disabled safely.", 503)
        status = await run([*command, "login", "status"], include_stderr=True)
        if b"Logged in" not in status:
            raise PreparationError(
                "Sign in with Codex CLI on this computer before preparing text.", 503
            )
        return mcp_controls

    @staticmethod
    def _check_working_directory(cwd: Path) -> None:
        if any((parent / ".git").exists() for parent in (cwd, *cwd.parents)):
            raise PreparationError(
                "Codex requires a system temporary directory outside a repository.", 503
            )

    async def availability(self) -> ProviderAvailability:
        try:
            if self._settings.error:
                raise PreparationError(self._settings.error, 503)
            command = resolve_executable(self._settings.codex_executable)
            with tempfile.TemporaryDirectory(prefix="shadowing-text-") as directory:
                cwd = Path(directory).resolve()
                self._check_working_directory(cwd)
                async with asyncio.timeout(15):
                    await self._probe(command, cwd, codex_environment(os.environ))
            return ProviderAvailability("codex", "Codex CLI", True)
        except PreparationError as exc:
            return ProviderAvailability("codex", "Codex CLI", False, exc.detail)
        except (OSError, UnicodeError, TimeoutError):
            return ProviderAvailability(
                "codex",
                "Codex CLI",
                False,
                "Codex CLI readiness could not be checked. Check its installation and login.",
            )

    async def prepare(self, source: str) -> list[str]:
        try:
            if self._settings.error:
                raise PreparationError(self._settings.error, 503)
            command = resolve_executable(self._settings.codex_executable)
            env = codex_environment(os.environ)
            async with asyncio.timeout(self._settings.timeout_seconds):
                with tempfile.TemporaryDirectory(prefix="shadowing-text-") as directory:
                    cwd = Path(directory).resolve()
                    self._check_working_directory(cwd)
                    mcp_controls = await self._probe(command, cwd, env)
                    schema = cwd / "proposal.schema.json"
                    output = cwd / "proposal.json"
                    instruction = cwd / "segmentation-instructions.txt"
                    schema.write_text(segmentation_schema(), encoding="utf-8")
                    instruction.write_text(segmentation_prompt(), encoding="utf-8")
                    arguments = [
                        *command,
                        "exec",
                        "--ignore-user-config",
                        "--ignore-rules",
                        "--ephemeral",
                        "--skip-git-repo-check",
                        "--sandbox",
                        "read-only",
                        "--strict-config",
                        "--output-schema",
                        str(schema),
                        "--output-last-message",
                        str(output),
                        "--json",
                        "--color",
                        "never",
                        *disabled_feature_arguments(),
                        *mcp_controls,
                        "-c",
                        'web_search="disabled"',
                        "-c",
                        "project_doc_max_bytes=0",
                        "-c",
                        'history.persistence="none"',
                        "-c",
                        'approval_policy="never"',
                        "-c",
                        f"model_instructions_file={json.dumps(str(instruction))}",
                        "-",
                    ]
                    result = await self._runner.run(
                        arguments,
                        cwd=cwd,
                        environment=env,
                        source=source.encode("utf-8"),
                        timeout=self._settings.timeout_seconds,
                        inspect_events=True,
                    )
                    if result.returncode:
                        raise PreparationError(
                            "Codex could not prepare the text. Check its login and try again."
                        )
                    events = [
                        check_codex_event(line)
                        for line in result.stdout.splitlines()
                        if line.strip()
                    ]
                    if not events or events[-1] != "turn.completed":
                        raise PreparationError(
                            "Codex did not finish preparing a complete proposal."
                        )
                    if (
                        not output.is_file()
                        or output.is_symlink()
                        or output.stat().st_size > MAX_OUTPUT_BYTES
                    ):
                        raise PreparationError("Codex did not return a valid bounded proposal.")
                    return parse_proposal(output.read_bytes())
        except TimeoutError as exc:
            raise PreparationError("Codex timed out. You can try preparing again.", 504) from exc
        except (OSError, UnicodeError) as exc:
            raise PreparationError(
                "Could not run Codex CLI. Check its installation and login.", 503
            ) from exc
