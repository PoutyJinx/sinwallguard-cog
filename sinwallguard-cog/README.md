# SINWallGuard

**SINWallGuard** is a Red-DiscordBot cog for keeping meme channels readable without killing conversation.
It lets moderators set per-channel word and/or character limits. Messages that exceed the configured limit are deleted, the user receives a lore-flavored SIN Corp warning, and repeated violations can trigger a short timeout.

Version **1.2.0** adds optional **thread containment**: long messages in the main channel can be redirected into a public thread where longer discussion is allowed. The main meme channel stays clean, but nobody has to abandon their forbidden thesis about cats, toast, or the ethics of pineapple on pizza.

## Features

- Per-channel word limits
- Per-channel character limits
- Recommended meme-channel preset: 30 words, 250 characters
- Optional thread containment for long discussions
- Reuses an existing open containment thread for the same user/channel when possible
- Messages inside threads are ignored by SINWallGuard, so longer discussion is allowed there
- Strike tracking per user/channel
- 3rd offense timeout by default
- Default timeout: 60 seconds
- Default strike reset: 10 minutes
- SIN Corp themed warning messages
- Optional moderator log channel for deleted text
- Deleted wall-text copied in safe code-block chunks
- Prefix commands and slash commands through Red hybrid commands
- Ignores bots, moderators, admins, and bot owners
- Ignores messages with no text content, such as attachment-only meme posts
- Counts links as short placeholders so long URLs do not unfairly punish users

## Installation

Replace `<repo_url>` with your GitHub repository URL.

```text
[p]repo add sinwallguard <repo_url>
[p]cog install sinwallguard sinwallguard
[p]load sinwallguard
```

For slash commands, sync after loading:

```text
[p]slash sync
```

Discord slash commands can take time to appear. Prefix commands work immediately.

## Recommended setup

For a meme channel:

```text
[p]sinwallguard meme #memes
```

That sets:

- 30 word limit
- 250 character limit
- 3 strikes
- 60 second timeout on the third strike
- 10 minute strike reset
- Thread containment enabled
- Thread auto-archive after 1440 minutes, Discord's 24-hour option
- Deleted text reposted inside the containment thread

If you already had the cog configured before v1.2.0, enable thread containment manually:

```text
[p]sinwallguard threadmode #memes true 1440 true
```

## Commands

Main command aliases for prefix commands:

```text
[p]sinwallguard
[p]swg
[p]wallguard
[p]textguard
```

Slash command group:

```text
/sinwallguard
```

### Setup commands

```text
[p]sinwallguard meme #memes
[p]sinwallguard set #memes 30 250
[p]sinwallguard words #memes 30
[p]sinwallguard chars #memes 250
[p]sinwallguard strikes #memes 3 60
[p]sinwallguard resettime #memes 10
[p]sinwallguard warntime #memes 45
[p]sinwallguard threadmode #memes true 1440 true
[p]sinwallguard logchannel #mod-log
[p]sinwallguard clearlog
[p]sinwallguard view #memes
[p]sinwallguard list
[p]sinwallguard disable #memes
[p]sinwallguard forget #memes
[p]sinwallguard clearstrikes
```

Slash equivalents are available under `/sinwallguard` once synced.

### Thread containment command

```text
[p]sinwallguard threadmode #memes true 1440 true
```

Arguments:

```text
channel: the text channel to protect
enabled: true or false
auto_archive_minutes: 60, 1440, 4320, or 10080
repost_deleted: true or false
```

Examples:

```text
[p]sinwallguard threadmode #memes true 1440 true
[p]sinwallguard threadmode #memes false 1440 true
[p]sinwallguard threadmode #memes true 60 false
```

When enabled, a long message in the main channel will be deleted, warned, and redirected into a public containment thread. Long messages inside threads are allowed and do not add strikes.

If the same user keeps posting long messages in the main channel while their containment thread is still open, SINWallGuard will try to reuse that thread and still add strikes for continuing outside the thread.

### Moderator log commands

```text
[p]sinwallguard logchannel #mod-log
[p]sinwallguard clearlog
```

When a wall-of-text message is deleted, SINWallGuard can copy the deleted text into the configured moderator channel as one or more `text` code blocks. Longer messages are split into safe chunks so the bot does not hit Discord's message length limit.

## Permissions

Moderators need one of these to configure the cog:

- Red moderator status, or
- `Manage Messages`

The bot should have:

- `Manage Messages` to delete violating messages
- `Moderate Members` to apply timeout punishments
- `Send Messages` to post warnings
- `Create Public Threads` for thread containment
- `Send Messages in Threads` to post inside containment threads
- `Send Messages` in the configured mod log channel, if logging is enabled

If the bot cannot delete, timeout, create a thread, or speak in a channel because of permissions or role hierarchy, it will skip that action instead of crashing the cog.

## Notes

- The cog does not punish attachment-only posts.
- Mod logging is server-wide and optional.
- Links are collapsed while counting so a single ugly URL does not trigger the wall guard by itself.
- Strikes are temporary and reset after the configured reset time.
- Strike data is memory-only and clears on bot restart.
- Active containment thread tracking is memory-only and clears on bot restart.
- Deleted message text is not stored in the cog's config. If thread reposting or mod logging is enabled, the text is copied into Discord messages in the relevant thread/log channel.
