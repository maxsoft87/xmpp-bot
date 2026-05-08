# Configuration Guide

## Overview

XMPP Bot uses two configuration files located in `/etc/xmpp_bot/`:

- `config.json` — Main bot configuration (JID, password, paths, settings)
- `commands.json` — Command definitions, user groups, and access control

Both files are created automatically with defaults on first run if they don't exist.

---

## Main Configuration (`config.json`)

### Location
```
/etc/xmpp_bot/config.json
```

### Default Values
```json
{
  "jid": null,
  "password": null,
  "storage_file": "/etc/xmpp_bot/omemo_storage.pkl",
  "commands_config": "/etc/xmpp_bot/commands.json",
  "scripts_dir": "/etc/xmpp_bot/scripts",
  "auto_reply": null,
  "omemo_enabled": true,
  "omemo_device_id": null,
  "log_level": "INFO"
}
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `jid` | string | `null` | Bot JID (e.g., `robot@example.com`) |
| `password` | string | `null` | Bot password |
| `storage_file` | string | `/etc/xmpp_bot/omemo_storage.pkl` | Path to OMEMO key storage file |
| `commands_config` | string | `/etc/xmpp_bot/commands.json` | Path to commands configuration file |
| `scripts_dir` | string | `/etc/xmpp_bot/scripts` | Directory for external command scripts |
| `auto_reply` | string or null | `null` | Auto-reply text for non-command messages. `null` disables |
| `omemo_enabled` | boolean | `true` | Enable/disable OMEMO encryption |
| `omemo_device_id` | integer or null | `null` | Specific OMEMO device ID. `null` generates automatically |
| `log_level` | string | `"INFO"` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

### Example
```json
{
  "jid": "robot@example.com",
  "password": "mysecretpassword",
  "storage_file": "/etc/xmpp_bot/omemo_storage.pkl",
  "commands_config": "/etc/xmpp_bot/commands.json",
  "scripts_dir": "/etc/xmpp_bot/scripts",
  "auto_reply": "I'm a bot. Use /help for available commands.",
  "omemo_enabled": true,
  "omemo_device_id": 12345,
  "log_level": "INFO"
}
```

### Notes

- **jid** and **password** must be set before first use. The bot will fail to start without them.
- **auto_reply** is sent only for non-command messages (text not starting with `/`).
- **omemo_enabled** changing requires bot restart.
- **log_level** changes are applied on reload without restart.
- **scripts_dir** is prepended to relative script paths in command definitions.

---

## Commands Configuration (`commands.json`)

### Location
```
/etc/xmpp_bot/commands.json
```

### Default Values
```json
{
  "groups": {
    "admins": [],
    "moderators": []
  },
  "commands": {
    "help": {
      "description": "Show available commands",
      "aliases": ["h", "?"],
      "script": null,
      "args": []
    },
    "ping": {
      "description": "Check connection - responds pong",
      "aliases": ["p"],
      "script": null,
      "args": []
    },
    "status": {
      "description": "Bot status and configuration",
      "aliases": ["s", "st"],
      "script": null,
      "args": [],
      "groups_only": ["admins"]
    },
    "reload": {
      "description": "Reload configuration",
      "aliases": ["r", "rl"],
      "script": null,
      "args": [],
      "groups_only": ["admins"]
    }
  }
}
```

### Groups Section

```json
{
  "groups": {
    "admins": ["admin@example.com", "superadmin@example.com"],
    "moderators": ["mod@example.com"],
    "users": ["user1@example.com", "user2@example.com"]
  }
}
```

- Group names are arbitrary strings
- Members are JID strings
- One JID can belong to multiple groups
- Groups are used with `groups_only` in command definitions

### Commands Section

#### Built-in Commands

Built-in commands (`help`, `ping`, `status`, `reload`) don't require a `script` field. Set `script` to `null`.

#### External Script Commands

```json
{
  "mycommand": {
    "description": "Description shown in /help",
    "aliases": ["mc", "my"],
    "script": "my_script.sh",
    "args": [
      {
        "name": "param1",
        "required": true
      },
      {
        "name": "param2",
        "required": false,
        "default": "value"
      }
    ],
    "groups_only": ["admins", "moderators"]
  }
}
```

### Command Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | Yes | Description shown in `/help` |
| `aliases` | array | No | Alternative command names (e.g., `["a", "alias"]`) |
| `script` | string or null | Yes | Script path. `null` for built-in commands. Relative paths use `scripts_dir` |
| `args` | array | No | List of argument definitions |
| `groups_only` | array | No | List of groups allowed to use this command. Empty or absent = public |

### Argument Definition

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Argument name (shown in help and error messages) |
| `required` | boolean | Yes | Whether argument is mandatory |
| `default` | any | No | Default value for optional arguments |

### Script Path Resolution

- **Absolute path** (`/usr/local/bin/script.sh`) — used as-is
- **Relative path** (`myscript.sh`) — prefixed with `scripts_dir` from `config.json`
- Script must be executable and exist

### Security Notes

- Commands with `groups_only` are completely hidden from unauthorized users in `/help`
- Unauthorized access attempts return "Unknown command" (same as non-existent commands)
- Failed access attempts are logged with WARNING level
- Always use absolute paths for scripts outside `scripts_dir`

---

## Hot Reload

Configuration can be reloaded without restart:

### Via XMPP Command
```
/reload
```

### Via System Signal
```bash
systemctl reload xmpp-bot
# or
kill -HUP <pid>
```

### Validated Fields on Reload
- `auto_reply` — updated immediately
- `log_level` — updated immediately
- `commands_config` — reloaded from new path if changed
- `scripts_dir` — updated immediately
- `omemo_enabled` — **requires restart**
- `jid` / `password` — **not reloaded** (requires restart)

### Validation Rules
- JSON must be valid
- `commands.json` must have `commands` section
- Referenced groups in `groups_only` must exist
- `log_level` must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **If validation fails, changes are rejected and old config remains active**

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PYTHONUNBUFFERED` | Set to `1` for unbuffered output (recommended for systemd) |

---

## File Permissions

```bash
chown -R xmpp_bot:xmpp_bot /etc/xmpp_bot
chmod 750 /etc/xmpp_bot
chmod 750 /etc/xmpp_bot/scripts
chmod 640 /etc/xmpp_bot/config.json
chmod 640 /etc/xmpp_bot/commands.json
chmod 640 /etc/xmpp_bot/omemo_storage.pkl
```

---

## Troubleshooting

### Bot fails to start
```bash
# Check config syntax
python3 -c "import json; json.load(open('/etc/xmpp_bot/config.json'))"

# Check logs
journalctl -u xmpp-bot -n 50
```

### Commands not loading
```bash
# Verify commands config path in main config
grep commands_config /etc/xmpp_bot/config.json

# Check commands config syntax
python3 -c "import json; json.load(open('/etc/xmpp_bot/commands.json'))"
```

### OMEMO issues
```bash
# Reset OMEMO storage (requires re-trust from contacts)
systemctl stop xmpp-bot
rm /etc/xmpp_bot/omemo_storage.pkl
systemctl start xmpp-bot
```

---
