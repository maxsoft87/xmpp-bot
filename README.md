# XMPP Bot - Feature Overview

## General Description
XMPP/Jabber bot with OMEMO end-to-end encryption support, a flexible command system from configuration files, group-based access control, and hot configuration reload.

---

## Operating Modes

### 1. Interactive Mode (`--listen`)
Runs as a daemon, connects to XMPP server, and waits for incoming messages.
```bash
xmpp_bot --listen
xmpp_bot --listen --debug
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
- Graceful fallback to unencrypted messages if OMEMO unavailable

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
  "log_level": "INFO"
}
```

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

### From DEB package
```bash
sudo dpkg -i xmpp-bot_1.0.0_amd64.deb
sudo nano /etc/xmpp_bot/config.json
sudo systemctl start xmpp-bot
```

### From RPM package
```bash
sudo rpm -ivh xmpp-bot-1.0.0-1.x86_64.rpm
sudo nano /etc/xmpp_bot/config.json
sudo systemctl start xmpp-bot
```

### From source
```bash
pip install slixmpp slixmpp_omemo omemo cryptography xeddsa
python send_xmpp.py --listen
```
- P.S. Build on Nuitka
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
| `-N, --no-omemo` | Disable OMEMO |
| `-c, --config` | Commands config path |
| `-d, --debug` | Debug logging |
| `-v, --version` | Show version |

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
