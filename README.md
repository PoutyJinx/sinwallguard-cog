# SINWallGuard

**SINWallGuard** is a Red-DiscordBot cog for keeping meme channels readable.
It lets moderators set per-channel word and/or character limits. Messages that exceed the configured limit are deleted, the user receives a lore-flavored SIN Corp warning, and repeated violations can trigger a short timeout.

Designed for channels where images, GIFs, and short captions are fine, but full doctoral essays about cats, toast, or the moral weight of memes should be contained.

## Features

- Per-channel word limits
- Per-channel character limits
- Recommended meme-channel preset: 30 words, 250 characters
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
- Parent-channel inheritance for threads

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
[p]sinwallguard logchannel #mod-log
[p]sinwallguard clearlog
[p]sinwallguard view #memes
[p]sinwallguard list
[p]sinwallguard disable #memes
```

Slash equivalents are available under `/sinwallguard` once synced.

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
- `Send Messages` in the configured mod log channel, if logging is enabled

If the bot cannot delete or timeout because of permissions or role hierarchy, it will still try to warn in the channel. If the bot cannot speak in the mod log channel, the deleted-text log will simply be skipped.

## Notes

- The cog does not punish attachment-only posts.
- Mod logging is server-wide and optional.
- Links are collapsed while counting so a single ugly URL does not trigger the wall guard by itself.
- Strikes are temporary and reset after the configured reset time.
- Strike data is memory-only and clears on bot restart.
