# Command System

## Overview

The command system allows defining custom slash-commands that execute external scripts or provide built-in functionality. Commands support argument validation, aliases, and group-based access control.

---

## Command Syntax

All commands start with `/`:
```
/command_name arg1 arg2 "argument with spaces"
```

### Parsing Rules
- Commands must start with `/`
- Arguments are space-separated
- Quoted arguments (`"..."`) preserve spaces
- Command names are case-insensitive
- Aliases are resolved before access checks

---

## Built-in Commands

### `/help` — Show Available Commands
```
/help
/h
/?
```
- Shows only commands available to the requesting user
- Group-restricted commands hidden from unauthorized users
- Displays aliases alongside main command names
- Shows argument requirements
- Admin users see group restrictions with 🔒 icon

**Output example (admin):**
```
🤖 XMPP Bot v7.0.0

Available commands:
  /help, /h, /? — Show available commands
  /ping, /p — Check connection - responds pong
  /reload, /r, /rl — Reload configuration 🔒 [groups: admins]
  /status, /s, /st — Bot status and configuration 🔒 [groups: admins]
```

**Output example (regular user):**
```
🤖 XMPP Bot v7.0.0

Available commands:
  /help, /h, /? — Show available commands
  /ping, /p — Check connection - responds pong
```

### `/ping` — Connection Check
```
/ping
/p
```
- Returns: `🏓 pong`
- Tests basic bot responsiveness

### `/status` — Bot Status
```
/status
/s
/st
```
- Returns detailed bot status: version, uptime, configuration paths, statistics
- Admin only (`groups_only: ["admins"]`)
- Password is masked in output

**Output:**
```
📊 Bot Status v7.0.0

🔧 General:
  JID: robot@example.com
  Password: my************rd
  OMEMO: ✅ Enabled
  Connected: ✅ Yes

⏱️ Uptime:
  Started: 2026-05-08 10:15:30
  Running: 2d 5h 30m 45s

📁 Configuration:
  Main config: /etc/xmpp_bot/config.json
  Commands config: /etc/xmpp_bot/commands.json
  Scripts directory: /etc/xmpp_bot/scripts
  Commands loaded: 2026-05-08 15:30:22

📈 Statistics:
  Commands: 6
  Aliases: 8
  Groups: 2
  admins: 2 members
  moderators: 1 members

💾 Storage:
  File: /etc/xmpp_bot/omemo_storage.pkl
  Size: 12,345 bytes
  Records: 42

📝 Logging:
  Level: INFO

💬 Auto-reply:
  Status: disabled
```

### `/reload` — Reload Configuration
```
/reload
/r
/rl
```
- Reloads `config.json` and `commands.json` without restart
- Validates configuration before applying
- Reports changes (added/removed commands and groups)
- Admin only

**Output:**
```
🔄 Commands config reloaded!
✅ Commands added: newcmd
🗑️ Commands removed: oldcmd
📊 Total: 7 commands, 2 groups
🕐 Config loaded: 2026-05-08 16:45:00
```

---

## Custom Commands

### Command Definition

```json
{
  "sheck": {
    "description": "Check if service is running",
    "aliases": ["check", "chk"],
    "script": "check_service.sh",
    "args": [
      {
        "name": "service",
        "required": true
      },
      {
        "name": "host",
        "required": false,
        "default": "localhost"
      }
    ],
    "groups_only": ["admins", "moderators"]
  }
}
```

### Usage
```
/check nginx
/check nginx 192.168.1.1
/check apache2
/chk mysql localhost
```

### Script Execution

When a command is invoked, the bot:
1. Checks user access rights
2. Resolves script path (adds `scripts_dir` prefix if relative)
3. Builds argument list: `[script_path, arg1, arg2, ...]`
4. Executes script asynchronously with 30-second timeout
5. Captures stdout (returns to user) and stderr (logged)

### Script Requirements
- Must be executable (`chmod +x`)
- Must exit with code 0 on success
- stdout is sent to user (first 1MB)
- stderr is logged as ERROR
- Timeout: 30 seconds

### Script Example
```bash
#!/bin/bash
# check_service.sh
SERVICE=$1
HOST=${2:-localhost}

if systemctl is-active --quiet $SERVICE; then
    echo "✅ Service $SERVICE is running on $HOST"
    exit 0
else
    echo "❌ Service $SERVICE is not running on $HOST"
    exit 1
fi
```

---

## Access Control

### Group Definition
```json
{
  "groups": {
    "admins": ["admin@example.com"],
    "moderators": ["mod1@example.com", "mod2@example.com"],
    "operators": ["op@example.com"]
  }
}
```

### Restricting Commands
```json
{
  "dangerous_cmd": {
    "groups_only": ["admins"]
  },
  "mod_cmd": {
    "groups_only": ["admins", "moderators"]
  },
  "public_cmd": {
    "groups_only": []
  }
}
```

### Access Rules
- Empty `groups_only` or absent = **public** (everyone can use)
- User must belong to **at least one** of the listed groups
- Unauthorized users:
  - Don't see the command in `/help`
  - Get "Unknown command" error when trying to use it
  - Attempt is logged as WARNING

### Group Membership
- One JID can belong to multiple groups
- Groups are defined in `commands.json`
- Changes applied on reload (no restart needed)
- Invalid JID format generates validation warning on reload

---

## Argument Handling

### Required Arguments
```json
{
  "args": [
    {"name": "filename", "required": true}
  ]
}
```
If not provided:
```
❌ Required argument missing: filename
Usage: /mycmd <filename>
```

### Optional Arguments with Defaults
```json
{
  "args": [
    {"name": "filename", "required": true},
    {"name": "mode", "required": false, "default": "fast"}
  ]
}
```

### Usage in Help
```
/mycmd, /mc <filename> [mode] — My command description
```

---

## Aliases

### Definition
```json
{
  "mycommand": {
    "aliases": ["mc", "my", "m"]
  }
}
```

### Usage
All these are equivalent:
```
/mycommand arg1
/mc arg1
/my arg1
/m arg1
```

### Rules
- Aliases are case-insensitive
- Duplicate aliases across commands generate warning
- Aliases inherit access control from parent command
- Hidden commands' aliases are also hidden

---

## Error Messages

| Message | Cause |
|---------|-------|
| `❌ Unknown command: /xxx` | Command doesn't exist or user lacks access |
| `❌ Command /xxx not configured` | Command has no script path |
| `❌ Execution error (script not found)` | Script file doesn't exist |
| `❌ Required argument missing: name` | Required argument not provided |
| `⏰ Command timed out` | Script exceeded 30 seconds |
| `❌ Execution error (code N)` | Script exited with non-zero code |
| `❌ Execution error (permission denied)` | Script not executable |

---

## Best Practices

1. **Use aliases** for frequently used commands
2. **Keep scripts in** `/etc/xmpp_bot/scripts/` with descriptive names
3. **Always validate input** in scripts (bot only passes arguments)
4. **Set appropriate timeout** (hardcoded at 30s, keep scripts fast)
5. **Use groups** for access control, not individual JIDs
6. **Test with `/reload`** after config changes
7. **Check logs** if commands don't work: `journalctl -u xmpp-bot -f`

---

## Security

- Commands execute as `xmpp_bot` user
- Scripts limited to `scripts_dir` by systemd sandbox
- No shell injection (arguments passed directly to script, not through shell)
- stderr is never sent to users
- Output limited to 1MB
- OMEMO encryption applied to command output when enabled
