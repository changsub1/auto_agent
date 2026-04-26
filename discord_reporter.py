"""Discord message helpers for run updates and Markdown artifacts."""

from __future__ import annotations

from pathlib import Path

import discord


DISCORD_MESSAGE_LIMIT = 2000
SAFE_CHUNK_SIZE = 1800


class DiscordReporter:
    """Send workflow updates to a Discord channel."""

    async def send_status(self, channel: discord.abc.Messageable, message: str) -> discord.Message:
        return await channel.send(message)

    async def send_markdown(
        self,
        channel: discord.abc.Messageable,
        *,
        title: str,
        content: str,
        artifact_path: Path | None = None,
    ) -> list[discord.Message]:
        messages: list[discord.Message] = []
        header = f"**{title}**"
        body = content.strip() or "(empty)"

        if len(header) + len(body) + 4 <= DISCORD_MESSAGE_LIMIT:
            messages.append(await channel.send(f"{header}\n{body}"))
            return messages

        first_chunk = body[:SAFE_CHUNK_SIZE].rstrip()
        suffix = "\n\n...truncated in Discord. Full content is saved locally."
        messages.append(await channel.send(f"{header}\n{first_chunk}{suffix}"))

        if artifact_path and artifact_path.exists():
            messages.append(
                await channel.send(
                    content=f"Full artifact: `{artifact_path}`",
                    file=discord.File(str(artifact_path)),
                )
            )
        else:
            for chunk in _chunks(body[SAFE_CHUNK_SIZE:], SAFE_CHUNK_SIZE):
                messages.append(await channel.send(chunk))

        return messages

    async def send_artifact_paths(
        self,
        channel: discord.abc.Messageable,
        *,
        run_dir: Path,
        generated_app_dir: Path | None = None,
        qa_report_path: Path | None = None,
        ok: bool | None = None,
    ) -> discord.Message:
        lines = [
            "**Run artifacts**",
            f"- Run directory: `{run_dir}`",
        ]
        if generated_app_dir:
            lines.append(f"- Generated app: `{generated_app_dir}`")
        if qa_report_path:
            lines.append(f"- QA report: `{qa_report_path}`")
        if ok is not None:
            lines.append(f"- QA status: {'PASS' if ok else 'FAIL'}")
        return await channel.send("\n".join(lines))

    async def send_files(
        self,
        channel: discord.abc.Messageable,
        *,
        title: str,
        paths: list[Path],
        limit: int = 4,
    ) -> list[discord.Message]:
        messages: list[discord.Message] = []
        existing_paths = [path for path in paths if path.exists()]
        if not existing_paths:
            messages.append(await channel.send(f"**{title}**\nNo files were produced."))
            return messages

        for path in existing_paths[:limit]:
            messages.append(
                await channel.send(
                    content=f"**{title}** `{path.name}`\n`{path}`",
                    file=discord.File(str(path)),
                )
            )
        if len(existing_paths) > limit:
            messages.append(await channel.send(f"{len(existing_paths) - limit} additional file(s) saved locally."))
        return messages


def _chunks(text: str, size: int) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size) if text[index : index + size]]
