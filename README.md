# XMPP Bot - Feature Overview

## General Description
XMPP/Jabber bot with OMEMO end-to-end encryption support, a flexible command system from configuration files, group-based access control, and hot configuration reload. Works in one-to-one chats and in OMEMO-encrypted group rooms (MUC).

---

## Operating Modes

### 1. Interactive Mode (`--listen`)
Runs as a daemon, connects to XMPP server, and waits for incoming messages.
```bash
xmpp_bot --listen
xmpp_bot --listen --debug
```

Rooms from `config.json` are joined automatically, or can be given on the command line:
```bash
xmpp_bot --listen --room ops@conference.example.com --nick botty
xmpp_bot --listen --room ops@conference.example.com --room alerts@conference.example.com
```

### 2. Single Message Mode
Sends a single message and exits.
```bash
xmpp_bot -j robot@example.com -p password -t user@example.com -m "Hello!"
```

### 3. File Transfer Mode
Sends images or files.
```bash
xmpp_bot -j robot@example.com -p password -t user@example.com -i photo.jpg -m "Check this out"
xmpp_bot -j robot@example.com -p password -t user@example.com -b "base64string"
xmpp_bot -j robot@example.com -p password -t user@example.com -s < image.jpg
```

---

## Key Features

### 🔐 OMEMO Encryption
- Automatic end-to-end encryption for all messages
- Trust management via automatic trust on first use (BTBV)
- Device list management and session handling
- Device list publication verified against PEP at startup
- Graceful fallback to unencrypted messages in one-to-one chats if OMEMO unavailable
- No plaintext fallback in group rooms — a group reply is either encrypted for every recipient or not sent at all

### 💬 Group Rooms (MUC, XEP-0045)
- Joins configured rooms after OMEMO keys are published
- Commands work in rooms exactly as in private chat; access control is applied to the sender's real JID
- Replies encrypted for all affiliated room members
- Join history suppressed, so stored commands are not replayed on reconnect
- Separate auto-reply for rooms with `{nick}`, `{jid}` and `{room}` placeholders
- Joined rooms and nicknames shown in `/status`

> **Note:** the bot needs to read the room affiliation lists to build the recipient set. If it cannot, group replies are skipped rather than sent unencrypted. Commands without `groups_only` are callable by any occupant, and their output goes to the whole room — review your access rules before joining shared rooms.

### 📁 Centralized Configuration
All configuration files located in `/etc/xmpp_bot/`:
- `config.json` - main bot configuration (JID, password, paths, settings)
- `commands.json` - command definitions, groups, and access control
- `omemo_storage.pkl` - OMEMO encryption keys and sessions

### 🛡️ Group-Based Access Control
- Define user groups in `commands.json`
- Restrict commands to specific groups via `groups_only` field
- Hidden commands: unauthorized users don't see restricted commands in `/help`
- Returns "Unknown command" for unauthorized access attempts

### 🏷️ Command Aliases
- Multiple shortcuts for the same command
- Built-in aliases: `/help` → `/h`, `/ping` → `/p`, `/status` → `/s`
- Custom aliases definable in `commands.json`

### 🔄 Hot Configuration Reload
Two ways to reload without restart:
1. **XMPP command:** `/reload` (admin only)
2. **System signal:** `systemctl reload xmpp-bot` or `kill -HUP <pid>`

Configuration validation before applying changes — broken configs are rejected.

### 📊 Status Monitoring
- `/status` command shows: version, uptime, connection state, config paths, statistics
- Password masking in status output
- Storage file size and record count

### 💬 Read Markers (XEP-0333)
- Sends "displayed" markers for incoming messages
- Clients show double-check or read indicator

### 🤖 Auto-Reply
- Configurable auto-reply for non-command messages
- Disabled by default (`null` in config)
- Can be set via `config.json` or `--auto-reply` argument

---

## Command System

### Built-in Commands
| Command | Aliases | Description | Access |
|---------|---------|-------------|--------|
| `/help` | `/h`, `/?` | Show available commands | Public |
| `/ping` | `/p` | Connection check | Public |
| `/status` | `/s`, `/st` | Bot status and stats | Admin |
| `/reload` | `/r`, `/rl` | Reload configuration | Admin |

### External Script Commands
Define custom commands in `commands.json`:
```json
{
  "uptime": {
    "description": "Show server uptime",
    "aliases": ["up"],
    "script": "uptime.sh",
    "args": [],
    "groups_only": ["admins"]
  }
}
```

- `script` - relative path (to `scripts_dir`) or absolute path
- `args` - required and optional arguments with defaults
- `groups_only` - restrict to specific groups
- `aliases` - alternative command names

---

## Configuration Files

### config.json
```json
{
  "jid": "robot@example.com",
  "password": "secret",
  "storage_file": "/etc/xmpp_bot/omemo_storage.pkl",
  "commands_config": "/etc/xmpp_bot/commands.json",
  "scripts_dir": "/etc/xmpp_bot/scripts",
  "auto_reply": null,
  "omemo_enabled": true,
  "omemo_device_id": null,
  "muc_rooms": [],
  "muc_nick": null,
  "muc_password": null,
  "muc_auto_reply": null,
  "log_level": "INFO"
}
```

### MUC rooms
`muc_rooms` accepts plain JIDs, or objects with a per-room nickname and password:
```json
{
  "muc_rooms": [
    "alerts@conference.example.com",
    {
      "jid": "ops@conference.example.com",
      "nick": "opsbot",
      "password": "roomsecret"
    }
  ],
  "muc_nick": "botty",
  "muc_password": null,
  "muc_auto_reply": "Hi {nick}, use /help for the command list"
}
```

- `muc_nick` — default nickname for rooms that don't set their own (falls back to the account localpart)
- `muc_password` — default password for password-protected rooms
- `muc_auto_reply` — reply to non-command messages in rooms; supports `{nick}`, `{jid}` and `{room}`. Leave `null` to stay silent.

### commands.json
```json
{
  "groups": {
    "admins": ["admin@example.com"],
    "moderators": ["mod@example.com"]
  },
  "commands": {
    "shell": {
      "description": "Execute shell command",
      "aliases": ["sh", "exec"],
      "script": "secure_shell.sh",
      "args": [{"name": "cmd", "required": true}],
      "groups_only": ["admins", "moderators"]
    }
  }
}
```

---

## Installation

Packages and the standalone binary are published on the
[Releases page](https://github.com/maxsoft87/xmpp-bot/releases).

### From DEB package
```bash
sudo dpkg -i xmpp-bot_8.0.1_amd64.deb
sudo nano /etc/xmpp_bot/config.json
sudo systemctl start xmpp-bot
```

### From RPM package
```bash
sudo rpm -ivh xmpp-bot-8.0.1-1.x86_64.rpm
sudo nano /etc/xmpp_bot/config.json
sudo systemctl start xmpp-bot
```

### From source
```bash
pip install slixmpp slixmpp_omemo omemo cryptography xeddsa aiohttp aiodns
python send_xmpp.py --listen
```

### Building a standalone binary
The binary is compiled with Nuitka in onefile mode:
```bash
./build.sh 8.0.1          # build, verify and deploy
DEPLOY=0 ./build.sh 8.0.1 # build and verify only
```
If `/tmp` on the target host is mounted `noexec`, build with a writable
extraction directory:
```bash
ONEFILE_TEMPDIR='{CACHE_DIR}/xmpp_bot/{VERSION}' ./build.sh 8.0.1
```

---

## CLI Arguments

| Argument | Description |
|----------|-------------|
| `-j, --jid` | Sender JID |
| `-p, --password` | Password |
| `-t, --to` | Recipient JID |
| `-m, --message` | Message text |
| `-i, --image` | Image file path |
| `-b, --base64` | Base64 image string |
| `--listen` | Daemon mode |
| `--auto-reply` | Auto-reply text for private chats |
| `--room` | MUC room JID to join (repeat for several rooms) |
| `--nick` | MUC nickname (defaults to the account localpart) |
| `--room-password` | Password for rooms given on the command line |
| `--muc-auto-reply` | Room auto-reply; supports `{nick}`, `{jid}`, `{room}` |
| `-N, --no-omemo` | Disable OMEMO |
| `-c, --config` | Commands config path |
| `-d, --debug` | Debug logging |
| `-v, --version` | Show version |

`--room` replaces the `muc_rooms` list from `config.json` when given.

---

## Requirements

- Python 3.8+
- slixmpp, slixmpp_omemo, omemo
- cryptography, xeddsa
- systemd (for service management)

---

## Versioning

Version is embedded at build time:
```bash
xmpp_bot --version  # shows version
/status             # shows version in XMPP
```

---

## Credits

OMEMO multi-user chat support contributed by [@1kamma](https://github.com/1kamma).

Built with [slixmpp](https://github.com/poezio/slixmpp),
[slixmpp-omemo](https://codeberg.org/poezio/slixmpp-omemo) and
[python-omemo](https://github.com/Syndace/python-omemo).
