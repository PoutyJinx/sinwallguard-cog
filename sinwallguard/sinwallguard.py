from __future__ import annotations

import datetime
import io
import re
import time
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red


URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w{2,32}:\d{15,25}>")
MENTION_RE = re.compile(r"<[@#][!&]?\d{15,25}>")
WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ'’-]+", re.UNICODE)


DEFAULT_CHANNEL_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "word_limit": None,
    "char_limit": None,
    "strike_limit": 3,
    "timeout_seconds": 60,
    "reset_after_minutes": 10,
    "warning_delete_after": 45,
}

DEFAULT_GUILD_SETTINGS: Dict[str, Any] = {
    "modlog_channel_id": None,
}

MEME_PRESET: Dict[str, Any] = {
    "enabled": True,
    "word_limit": 30,
    "char_limit": 250,
    "strike_limit": 3,
    "timeout_seconds": 60,
    "reset_after_minutes": 10,
    "warning_delete_after": 45,
}


class SINWallGuard(commands.Cog):
    """SIN Corp wall-of-text containment for meme channels."""

    __author__ = ["Jinx", "NODE-13"]
    __version__ = "1.1.0"

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=83746190256413, force_registration=True)
        self.config.register_guild(channels={}, **DEFAULT_GUILD_SETTINGS)
        # Memory-only strikes: (guild_id, configured_channel_id, user_id) -> {count, last}
        self._strikes: Dict[Tuple[int, int, int], Dict[str, float]] = {}

    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\n\nCog Version: {self.__version__}"

    async def red_get_data_for_user(self, *, user_id: int) -> Mapping[str, io.BytesIO]:
        # Strike data is temporary and in-memory only, and no message content is stored.
        return {}

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        # Remove temporary in-memory strikes for this user, if any exist.
        self._strikes = {
            key: value for key, value in self._strikes.items() if key[2] != user_id
        }

    # ----------------------------
    # Message listener
    # ----------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or not isinstance(message.author, discord.Member):
            return

        if message.author.bot or message.webhook_id is not None:
            return

        if not message.content or not message.content.strip():
            # Attachment-only memes, stickers, and similar posts are allowed.
            return

        if await self._is_exempt(message.author):
            return

        # Do not eat normal prefix commands if someone happens to use them in a guarded channel.
        try:
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return
        except Exception:
            pass

        configured_channel_id, settings = await self._settings_for_message(message)
        if not configured_channel_id or not settings:
            return

        word_count, char_count = self._count_message(message.content)
        violations = self._get_violations(settings, word_count, char_count)
        if not violations:
            return

        await self._handle_violation(
            message=message,
            configured_channel_id=configured_channel_id,
            settings=settings,
            word_count=word_count,
            char_count=char_count,
            violations=violations,
        )

    async def _settings_for_message(
        self, message: discord.Message
    ) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        guild = message.guild
        if guild is None:
            return None, None

        channel_settings = await self.config.guild(guild).channels()
        candidates = [message.channel.id]

        # Threads inherit the parent channel's limit if the thread itself is not configured.
        parent_id = getattr(message.channel, "parent_id", None)
        if parent_id:
            candidates.append(parent_id)

        for channel_id in candidates:
            raw = channel_settings.get(str(channel_id))
            if not raw:
                continue
            settings = self._merged_settings(raw)
            if settings.get("enabled"):
                return int(channel_id), settings

        return None, None

    async def _is_exempt(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
            return True

        try:
            if await self.bot.is_owner(member):
                return True
        except Exception:
            pass

        try:
            if await self.bot.is_mod(member):
                return True
        except Exception:
            pass

        return False

    def _count_message(self, content: str) -> Tuple[int, int]:
        normalized = URL_RE.sub(" link ", content)
        normalized = CUSTOM_EMOJI_RE.sub(" emoji ", normalized)
        normalized = MENTION_RE.sub(" mention ", normalized)
        normalized = " ".join(normalized.split())

        word_count = len(WORD_RE.findall(normalized))
        char_count = len(normalized)
        return word_count, char_count

    def _get_violations(
        self, settings: Dict[str, Any], word_count: int, char_count: int
    ) -> Dict[str, Tuple[int, int]]:
        violations: Dict[str, Tuple[int, int]] = {}
        word_limit = settings.get("word_limit")
        char_limit = settings.get("char_limit")

        if isinstance(word_limit, int) and word_limit > 0 and word_count > word_limit:
            violations["words"] = (word_count, word_limit)

        if isinstance(char_limit, int) and char_limit > 0 and char_count > char_limit:
            violations["characters"] = (char_count, char_limit)

        return violations

    async def _handle_violation(
        self,
        message: discord.Message,
        configured_channel_id: int,
        settings: Dict[str, Any],
        word_count: int,
        char_count: int,
        violations: Dict[str, Tuple[int, int]],
    ) -> None:
        deleted = False
        try:
            await message.delete()
            deleted = True
        except discord.Forbidden:
            deleted = False
        except discord.HTTPException:
            deleted = False

        strike_count = self._add_strike(
            guild_id=message.guild.id,
            channel_id=configured_channel_id,
            user_id=message.author.id,
            reset_after_minutes=int(settings.get("reset_after_minutes", 10)),
        )

        strike_limit = max(1, int(settings.get("strike_limit", 3)))
        timeout_seconds = max(0, int(settings.get("timeout_seconds", 60)))
        should_timeout = strike_count >= strike_limit and timeout_seconds > 0
        timed_out = False
        timeout_failed = False

        if should_timeout:
            timed_out = await self._timeout_member(
                member=message.author,
                seconds=timeout_seconds,
                reason="SINWallGuard repeated wall-of-text violation",
            )
            timeout_failed = not timed_out
            self._clear_strikes(message.guild.id, configured_channel_id, message.author.id)

        notice = self._build_notice(
            member=message.author,
            settings=settings,
            strike_count=strike_count,
            strike_limit=strike_limit,
            word_count=word_count,
            char_count=char_count,
            violations=violations,
            deleted=deleted,
            should_timeout=should_timeout,
            timed_out=timed_out,
            timeout_failed=timeout_failed,
        )

        delete_after = settings.get("warning_delete_after", 45)
        if not isinstance(delete_after, int) or delete_after <= 0:
            delete_after = None

        try:
            await message.channel.send(
                notice,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                delete_after=delete_after,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        await self._send_modlog(
            message=message,
            configured_channel_id=configured_channel_id,
            settings=settings,
            word_count=word_count,
            char_count=char_count,
            violations=violations,
            strike_count=strike_count,
            strike_limit=strike_limit,
            deleted=deleted,
            timed_out=timed_out,
            timeout_failed=timeout_failed,
        )

    async def _send_modlog(
        self,
        message: discord.Message,
        configured_channel_id: int,
        settings: Dict[str, Any],
        word_count: int,
        char_count: int,
        violations: Dict[str, Tuple[int, int]],
        strike_count: int,
        strike_limit: int,
        deleted: bool,
        timed_out: bool,
        timeout_failed: bool,
    ) -> None:
        if message.guild is None:
            return

        modlog_channel_id = await self.config.guild(message.guild).modlog_channel_id()
        if not modlog_channel_id:
            return

        channel = message.guild.get_channel(int(modlog_channel_id))
        if channel is None:
            try:
                fetched = await self.bot.fetch_channel(int(modlog_channel_id))
            except (discord.Forbidden, discord.HTTPException, ValueError):
                return
            if not isinstance(fetched, discord.TextChannel):
                return
            channel = fetched

        if not isinstance(channel, discord.TextChannel):
            return

        source_channel = message.channel
        configured_channel = message.guild.get_channel(configured_channel_id)
        configured_name = configured_channel.mention if configured_channel else f"`{configured_channel_id}`"
        source_name = getattr(source_channel, "mention", f"`{source_channel.id}`")

        violation_text = ", ".join(
            f"{label}: {actual}/{limit}" for label, (actual, limit) in violations.items()
        )
        action_bits = ["deleted" if deleted else "delete failed"]
        if timed_out:
            action_bits.append(f"timed out for {self._human_duration(int(settings.get('timeout_seconds', 60)))}")
        elif timeout_failed:
            action_bits.append("timeout failed")

        created_at = discord.utils.format_dt(message.created_at, style="F")
        jump_url = getattr(message, "jump_url", None)
        jump_line = f"\nJump URL: {jump_url}" if jump_url else ""

        header = (
            "**SINWallGuard Mod Log**\n"
            f"User: {message.author.mention} (`{message.author.id}`)\n"
            f"Channel: {source_name} | Config: {configured_name}\n"
            f"When: {created_at}\n"
            f"Action: **{', '.join(action_bits)}**\n"
            f"Strikes: **{min(strike_count, strike_limit)}/{strike_limit}**\n"
            f"Detected: **{word_count} words** / **{char_count} characters**\n"
            f"Violation: **{violation_text}**"
            f"{jump_line}\n"
            "Deleted text:"
        )

        try:
            await channel.send(
                header,
                allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
            )
            for chunk in self._codeblock_chunks(message.content):
                await channel.send(
                    chunk,
                    allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
                )

            if message.attachments:
                attachment_lines = [
                    f"• {attachment.filename}: {attachment.url}" for attachment in message.attachments
                ]
                await channel.send(
                    "Attachments on deleted message:\n" + "\n".join(attachment_lines),
                    allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
                )
        except (discord.Forbidden, discord.HTTPException):
            return

    def _codeblock_chunks(self, content: str):
        # Discord bot messages are capped, and code fences need room too.
        # Splitting keeps the mod log from failing on giant text walls.
        safe_content = content.replace("```", "`\u200b``")
        max_body_length = 1850
        if not safe_content:
            yield "```text\n[empty message content]\n```"
            return

        start = 0
        total_length = len(safe_content)
        while start < total_length:
            chunk = safe_content[start : start + max_body_length]
            start += max_body_length
            yield f"```text\n{chunk}\n```"

    def _add_strike(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        reset_after_minutes: int,
    ) -> int:
        key = (guild_id, channel_id, user_id)
        now = time.monotonic()
        reset_after_seconds = max(60, reset_after_minutes * 60)
        data = self._strikes.get(key)

        if not data or now - data.get("last", 0.0) > reset_after_seconds:
            data = {"count": 0.0, "last": now}

        data["count"] = data.get("count", 0.0) + 1
        data["last"] = now
        self._strikes[key] = data
        return int(data["count"])

    def _clear_strikes(self, guild_id: int, channel_id: int, user_id: int) -> None:
        self._strikes.pop((guild_id, channel_id, user_id), None)

    async def _timeout_member(self, member: discord.Member, seconds: int, reason: str) -> bool:
        try:
            await member.timeout(datetime.timedelta(seconds=seconds), reason=reason)
            return True
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return False

    def _build_notice(
        self,
        member: discord.Member,
        settings: Dict[str, Any],
        strike_count: int,
        strike_limit: int,
        word_count: int,
        char_count: int,
        violations: Dict[str, Tuple[int, int]],
        deleted: bool,
        should_timeout: bool,
        timed_out: bool,
        timeout_failed: bool,
    ) -> str:
        limits = self._limit_text(settings)
        timeout_seconds = int(settings.get("timeout_seconds", 60))
        reset_minutes = int(settings.get("reset_after_minutes", 10))

        detected = f"Detected: **{word_count} words** / **{char_count} characters**."
        strike_text = f"Strike **{min(strike_count, strike_limit)}/{strike_limit}**."
        delete_text = "Your message was deleted." if deleted else "I tried to delete it, but my claws lacked permission."

        if timed_out:
            title = "**SIN Corp Containment Action**"
            body = (
                f"{member.mention}, excessive wall-of-text activity has breached containment.\n"
                f"{delete_text}\n"
                f"You have been placed in a **{self._human_duration(timeout_seconds)} timeout** "
                f"for the safety of the meme department."
            )
        elif should_timeout and timeout_failed:
            title = "**SIN Corp Containment Attempt Failed**"
            body = (
                f"{member.mention}, you reached the containment threshold, but I could not apply the timeout.\n"
                f"{delete_text}\n"
                f"Please check my **Moderate Members** permission and role hierarchy before the toast essays evolve."
            )
        elif strike_count >= max(1, strike_limit - 1):
            title = "**SIN Corp Final Notice**"
            body = (
                f"{member.mention}, your text wall has breached containment again.\n"
                f"This channel is for memes, not a doctoral thesis on toast.\n"
                f"{delete_text}\n"
                f"One more violation may result in a **{self._human_duration(timeout_seconds)} timeout**."
            )
        else:
            title = "**SIN Corp Compliance Notice**"
            body = (
                f"{member.mention}, your message exceeded the approved meme-channel containment limit.\n"
                f"{delete_text}\n"
                f"Please keep posts under **{limits}** so the archives remain readable."
            )

        footer = (
            f"\nLimit: **{limits}**. {detected} {strike_text} "
            f"Strikes reset after **{reset_minutes} minutes**."
        )
        return f"{title}\n{body}{footer}"

    def _human_duration(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        if seconds == 60:
            return "1 minute"
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        minutes = seconds // 60
        remaining = seconds % 60
        if remaining == 0:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        return f"{minutes} minute{'s' if minutes != 1 else ''} {remaining} second{'s' if remaining != 1 else ''}"

    # ----------------------------
    # Config helpers
    # ----------------------------

    def _merged_settings(self, raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        settings = dict(DEFAULT_CHANNEL_SETTINGS)
        if raw:
            settings.update(raw)
        return settings

    async def _get_channel_settings(
        self, guild: discord.Guild, channel_id: int
    ) -> Dict[str, Any]:
        channels = await self.config.guild(guild).channels()
        return self._merged_settings(channels.get(str(channel_id)))

    async def _set_channel_settings(
        self, guild: discord.Guild, channel_id: int, **updates: Any
    ) -> Dict[str, Any]:
        async with self.config.guild(guild).channels() as channels:
            settings = self._merged_settings(channels.get(str(channel_id)))
            settings.update(updates)
            channels[str(channel_id)] = settings
            return settings

    async def _remove_channel_settings(self, guild: discord.Guild, channel_id: int) -> None:
        async with self.config.guild(guild).channels() as channels:
            channels.pop(str(channel_id), None)

    def _limit_text(self, settings: Dict[str, Any]) -> str:
        pieces = []
        word_limit = settings.get("word_limit")
        char_limit = settings.get("char_limit")

        if isinstance(word_limit, int) and word_limit > 0:
            pieces.append(f"{word_limit} words")
        if isinstance(char_limit, int) and char_limit > 0:
            pieces.append(f"{char_limit} characters")

        if not pieces:
            return "no active limit"
        return " / ".join(pieces)

    def _settings_summary(self, settings: Dict[str, Any]) -> str:
        enabled = "Enabled" if settings.get("enabled") else "Disabled"
        timeout_seconds = int(settings.get("timeout_seconds", 60))
        warning_delete_after = settings.get("warning_delete_after", 45)
        warning_text = "never" if not warning_delete_after else f"{warning_delete_after}s"
        return (
            f"Status: **{enabled}**\n"
            f"Limit: **{self._limit_text(settings)}**\n"
            f"Strikes: **{settings.get('strike_limit', 3)}**\n"
            f"Timeout: **{self._human_duration(timeout_seconds)}**\n"
            f"Strike reset: **{settings.get('reset_after_minutes', 10)} minutes**\n"
            f"Warning cleanup: **{warning_text}**"
        )

    def _validate_limit(self, amount: Optional[int], name: str) -> Optional[str]:
        if amount is None:
            return None
        if amount < 0:
            return f"{name} cannot be negative. Use `0` to disable that limit."
        if amount > 5000:
            return f"{name} is too high. Please use 5000 or lower."
        return None

    def _normalize_limit(self, amount: Optional[int]) -> Optional[int]:
        if amount is None:
            return None
        return None if amount == 0 else int(amount)

    async def _send_help_text(self, ctx: commands.Context) -> None:
        prefix = ctx.clean_prefix
        text = (
            "**SINWallGuard** keeps meme channels from turning into forbidden literature.\n\n"
            "**Recommended meme setup:**\n"
            f"`{prefix}sinwallguard meme #memes`\n\n"
            "**Manual setup:**\n"
            f"`{prefix}sinwallguard set #memes 30 250`\n"
            f"`{prefix}sinwallguard words #memes 30`\n"
            f"`{prefix}sinwallguard chars #memes 250`\n"
            f"`{prefix}sinwallguard strikes #memes 3 60`\n"
            f"`{prefix}sinwallguard resettime #memes 10`\n"
            f"`{prefix}sinwallguard logchannel #mod-log`\n"
            f"`{prefix}sinwallguard clearlog`\n"
            f"`{prefix}sinwallguard view #memes`\n"
            f"`{prefix}sinwallguard disable #memes`\n\n"
            "Slash versions are available under `/sinwallguard` after syncing."
        )
        await ctx.send(text)

    # ----------------------------
    # Commands
    # ----------------------------

    @commands.hybrid_group(
        name="sinwallguard",
        aliases=["swg", "wallguard", "textguard"],
        invoke_without_command=True,
    )
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard(self, ctx: commands.Context) -> None:
        """Manage SINWallGuard text containment."""
        await self._send_help_text(ctx)

    @sinwallguard.command(name="help")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_help(self, ctx: commands.Context) -> None:
        """Show SINWallGuard help."""
        await self._send_help_text(ctx)

    @sinwallguard.command(name="meme")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_meme(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Apply the recommended meme-channel preset."""
        settings = await self._set_channel_settings(ctx.guild, channel.id, **MEME_PRESET)
        await ctx.send(
            f"**SIN Corp Meme Containment installed in {channel.mention}.**\n"
            f"{self._settings_summary(settings)}"
        )

    @sinwallguard.command(name="set")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_set(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        word_limit: Optional[int] = None,
        char_limit: Optional[int] = None,
    ) -> None:
        """Enable or update limits for a channel."""
        error = self._validate_limit(word_limit, "Word limit") or self._validate_limit(
            char_limit, "Character limit"
        )
        if error:
            await ctx.send(error)
            return

        updates: Dict[str, Any] = {"enabled": True}
        if word_limit is None and char_limit is None:
            updates["word_limit"] = 30
            updates["char_limit"] = 250
        else:
            if word_limit is not None:
                updates["word_limit"] = self._normalize_limit(word_limit)
            if char_limit is not None:
                updates["char_limit"] = self._normalize_limit(char_limit)

        settings = await self._set_channel_settings(ctx.guild, channel.id, **updates)
        await ctx.send(
            f"**SINWallGuard updated for {channel.mention}.**\n{self._settings_summary(settings)}"
        )

    @sinwallguard.command(name="words")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_words(
        self, ctx: commands.Context, channel: discord.TextChannel, amount: int
    ) -> None:
        """Set the word limit. Use 0 to disable it."""
        error = self._validate_limit(amount, "Word limit")
        if error:
            await ctx.send(error)
            return

        settings = await self._set_channel_settings(
            ctx.guild, channel.id, enabled=True, word_limit=self._normalize_limit(amount)
        )
        await ctx.send(
            f"**Word containment updated for {channel.mention}.**\n{self._settings_summary(settings)}"
        )

    @sinwallguard.command(name="chars")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_chars(
        self, ctx: commands.Context, channel: discord.TextChannel, amount: int
    ) -> None:
        """Set the character limit. Use 0 to disable it."""
        error = self._validate_limit(amount, "Character limit")
        if error:
            await ctx.send(error)
            return

        settings = await self._set_channel_settings(
            ctx.guild, channel.id, enabled=True, char_limit=self._normalize_limit(amount)
        )
        await ctx.send(
            f"**Character containment updated for {channel.mention}.**\n{self._settings_summary(settings)}"
        )

    @sinwallguard.command(name="strikes")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_strikes(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        strike_limit: int = 3,
        timeout_seconds: int = 60,
    ) -> None:
        """Set strikes before timeout and timeout length."""
        if strike_limit < 1 or strike_limit > 10:
            await ctx.send("Strike limit must be between 1 and 10.")
            return
        if timeout_seconds < 0 or timeout_seconds > 2419200:
            await ctx.send("Timeout seconds must be between 0 and 2419200. Use 0 to disable timeouts.")
            return

        settings = await self._set_channel_settings(
            ctx.guild,
            channel.id,
            enabled=True,
            strike_limit=strike_limit,
            timeout_seconds=timeout_seconds,
        )
        await ctx.send(
            f"**Strike containment updated for {channel.mention}.**\n{self._settings_summary(settings)}"
        )

    @sinwallguard.command(name="resettime")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_resettime(
        self, ctx: commands.Context, channel: discord.TextChannel, minutes: int = 10
    ) -> None:
        """Set how long before strikes reset."""
        if minutes < 1 or minutes > 1440:
            await ctx.send("Reset time must be between 1 and 1440 minutes.")
            return

        settings = await self._set_channel_settings(
            ctx.guild, channel.id, enabled=True, reset_after_minutes=minutes
        )
        await ctx.send(
            f"**Strike reset updated for {channel.mention}.**\n{self._settings_summary(settings)}"
        )

    @sinwallguard.command(name="warntime")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_warntime(
        self, ctx: commands.Context, channel: discord.TextChannel, seconds: int = 45
    ) -> None:
        """Set how long warnings stay visible. Use 0 to keep them."""
        if seconds < 0 or seconds > 300:
            await ctx.send("Warning cleanup must be between 0 and 300 seconds.")
            return

        settings = await self._set_channel_settings(
            ctx.guild, channel.id, enabled=True, warning_delete_after=seconds
        )
        await ctx.send(
            f"**Warning cleanup updated for {channel.mention}.**\n{self._settings_summary(settings)}"
        )

    @sinwallguard.command(name="logchannel")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_logchannel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Set the moderator log channel."""
        permissions = channel.permissions_for(ctx.guild.me)
        warning = ""
        if not permissions.send_messages:
            warning = "\n⚠️ I do not currently have **Send Messages** in that channel."

        await self.config.guild(ctx.guild).modlog_channel_id.set(channel.id)
        await ctx.send(
            f"**SINWallGuard mod log channel set to {channel.mention}.**\n"
            "Deleted wall-text will be copied there in safe code-block chunks."
            f"{warning}"
        )

    @sinwallguard.command(name="clearlog")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_clearlog(self, ctx: commands.Context) -> None:
        """Disable the moderator log channel."""
        await self.config.guild(ctx.guild).modlog_channel_id.clear()
        await ctx.send("**SINWallGuard mod logging disabled.** The paperwork chute has been sealed.")

    @sinwallguard.command(name="view")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_view(
        self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None
    ) -> None:
        """View SINWallGuard settings for a channel."""
        channel = channel or ctx.channel
        if not isinstance(channel, discord.TextChannel):
            await ctx.send("Please choose a normal text channel.")
            return

        settings = await self._get_channel_settings(ctx.guild, channel.id)
        modlog_channel_id = await self.config.guild(ctx.guild).modlog_channel_id()
        modlog_channel = ctx.guild.get_channel(int(modlog_channel_id)) if modlog_channel_id else None
        modlog_text = modlog_channel.mention if modlog_channel else ("disabled" if not modlog_channel_id else f"missing channel `{modlog_channel_id}`")
        await ctx.send(
            f"**SINWallGuard settings for {channel.mention}:**\n"
            f"{self._settings_summary(settings)}\n"
            f"Mod log: **{modlog_text}**"
        )

    @sinwallguard.command(name="list")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_list(self, ctx: commands.Context) -> None:
        """List all configured channels."""
        channels = await self.config.guild(ctx.guild).channels()
        if not channels:
            await ctx.send("No channels are currently registered with SINWallGuard.")
            return

        lines = []
        for channel_id, raw_settings in channels.items():
            channel = ctx.guild.get_channel(int(channel_id))
            settings = self._merged_settings(raw_settings)
            name = channel.mention if channel else f"Deleted channel `{channel_id}`"
            state = "ON" if settings.get("enabled") else "OFF"
            lines.append(f"• {name}: **{state}**, {self._limit_text(settings)}")

        await ctx.send("**SINWallGuard registered channels:**\n" + "\n".join(lines))

    @sinwallguard.command(name="disable")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_disable(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Disable SINWallGuard in a channel."""
        settings = await self._set_channel_settings(ctx.guild, channel.id, enabled=False)
        await ctx.send(
            f"**SINWallGuard disabled for {channel.mention}.**\n{self._settings_summary(settings)}"
        )

    @sinwallguard.command(name="forget")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_forget(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Remove saved settings for a channel entirely."""
        await self._remove_channel_settings(ctx.guild, channel.id)
        await ctx.send(f"**SINWallGuard forgot {channel.mention}.** The paperwork has been shredded.")

    @sinwallguard.command(name="clearstrikes")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def sinwallguard_clearstrikes(
        self,
        ctx: commands.Context,
        member: Optional[discord.Member] = None,
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        """Clear temporary strikes for one member or everyone."""
        guild_id = ctx.guild.id
        channel_id = channel.id if channel else None
        member_id = member.id if member else None

        before = len(self._strikes)
        self._strikes = {
            key: value
            for key, value in self._strikes.items()
            if not (
                key[0] == guild_id
                and (channel_id is None or key[1] == channel_id)
                and (member_id is None or key[2] == member_id)
            )
        }
        removed = before - len(self._strikes)

        target_bits = []
        if member:
            target_bits.append(member.mention)
        else:
            target_bits.append("everyone")
        if channel:
            target_bits.append(f"in {channel.mention}")

        await ctx.send(
            f"Cleared **{removed}** temporary strike entr{'y' if removed == 1 else 'ies'} for {' '.join(target_bits)}."
        )
