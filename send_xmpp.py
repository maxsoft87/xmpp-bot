#!/usr/bin/env python3
"""XMPP/Jabber client with OMEMO and command system from config"""
import argparse, asyncio, base64, json, logging, mimetypes, os, pickle, re, shlex, signal, subprocess, sys, tempfile, traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Set, Dict, Optional, List

from slixmpp import ClientXMPP, JID
from slixmpp_omemo import XEP_0384, TrustLevel
from omemo.storage import Storage, Just, Nothing

# Build version
__version__ = "7.0.0"

# === Centralized configuration ===
CONFIG_DIR = "/etc/xmpp_bot"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
SCRIPTS_DIR = os.path.join(CONFIG_DIR, "scripts")

STORAGE_FILE = os.path.join(CONFIG_DIR, "omemo_storage.pkl")
CONFIG_FILE_BOT = os.path.join(CONFIG_DIR, "commands.json")

DEFAULT_MAIN_CONFIG = {
    "jid": None,
    "password": None,
    "storage_file": STORAGE_FILE,
    "commands_config": CONFIG_FILE_BOT,
    "scripts_dir": SCRIPTS_DIR,
    "auto_reply": None,
    "omemo_enabled": True,
    "omemo_device_id": None,
    "log_level": "INFO"
}

DEFAULT_COMMANDS_CONFIG = {
    "groups": {
        "admins": [],
        "moderators": []
    },
    "commands": {
        "help": {
            "description": "Show available commands",
            "aliases": ["h", "?"],
            "script": None,
            "args": []
        },
        "ping": {
            "description": "Check connection - responds pong",
            "aliases": ["p"],
            "script": None,
            "args": []
        },
        "status": {
            "description": "Bot status and configuration",
            "aliases": ["s", "st"],
            "script": None,
            "args": [],
            "groups_only": ["admins"]
        },
        "reload": {
            "description": "Reload configuration",
            "aliases": ["r", "rl"],
            "script": None,
            "args": [],
            "groups_only": ["admins"]
        }
    }
}


def load_main_config(config_path: str) -> dict:
    """Load main config from JSON file."""
    config = DEFAULT_MAIN_CONFIG.copy()
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
            config.update(file_config)
            logging.info(f"Main config loaded from {config_path}")
        except Exception as e:
            logging.error(f"Error loading main config {config_path}: {e}. Using defaults.")
    else:
        logging.warning(f"Main config {config_path} not found. Using defaults.")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logging.info(f"Default main config created: {config_path}")
        except Exception as e:
            logging.error(f"Failed to create default config: {e}")
    return config


def mask_password(password: str) -> str:
    """Mask password for safe display"""
    if not password:
        return "not set"
    if len(password) <= 4:
        return "*" * len(password)
    return password[:2] + "*" * (len(password) - 4) + password[-2:]


def format_uptime(start_time: datetime) -> str:
    """Format uptime"""
    if not start_time:
        return "unknown"
    delta = datetime.now() - start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


class DictStorage(Storage):
    """OMEMO data storage with pickle support."""
    def __init__(self):
        self._Storage__cache = None
        self._data = {}

    def save_sync(self, path):
        with open(path, 'wb') as f:
            pickle.dump(self._data, f)

    def load_sync(self, path):
        if os.path.exists(path):
            with open(path, 'rb') as f:
                self._data = pickle.load(f)

    async def _load(self, k):
        v = self._data.get(k)
        return Just(v) if v is not None else Nothing()

    async def _store(self, k, v):
        self._data[k] = v

    async def _delete(self, k):
        self._data.pop(k, None)

    async def load(self, k): return await self._load(k)
    async def store(self, k, v): await self._store(k, v)
    async def delete(self, k): await self._delete(k)
    async def load_primitive(self, k, _): return await self._load(k)
    async def store_primitive(self, k, v): await self._store(k, v)
    async def delete_primitive(self, k): await self._delete(k)
    async def load_bundle(self, k): return await self._load(k)
    async def store_bundle(self, k, v): await self._store(k, v)

    async def load_optional(self, k, _):
        v = self._data.get(k)
        if v is None:
            if '/label' in k:
                return Just(None)
            return Nothing()
        return Just(v)

    async def store_optional(self, k, v):
        if v is not None or '/label' not in k:
            self._data[k] = v


class WorkingOMEMO:
    """OMEMO plugin wrapper"""
    def __init__(self, xmpp):
        self.xmpp = xmpp
        self.plugin = xmpp.plugin._plugins['xep_0384']

    async def get_session_manager(self): return await self.plugin.get_session_manager()
    async def encrypt_message(self, msg, recipients: Set[JID]): return await self.plugin.encrypt_message(msg, recipients)
    async def decrypt_message(self, msg): return await self.plugin.decrypt_message(msg)
    def is_encrypted(self, msg): return self.plugin.is_encrypted(msg)

    async def session_bind(self, jid):
        result = self.plugin.session_bind(jid)
        if asyncio.iscoroutine(result):
            await result


class CommandHandler:
    """Command handler with group access, aliases and hot reload"""

    def __init__(self, config_path: str, scripts_dir: str = SCRIPTS_DIR):
        self.config_path = config_path
        self.scripts_dir = scripts_dir
        self.commands: Dict = {}
        self.groups: Dict[str, List[str]] = {}
        self.aliases: Dict[str, str] = {}
        self.last_loaded_time = None
        self.load_config()

    def load_config(self):
        """Load config from file or create with defaults"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                old_commands_count = len(self.commands)
                self.commands = config.get('commands', {})
                self.groups = config.get('groups', {})
                self._build_aliases()
                self.last_loaded_time = datetime.now()
                logging.info(f"Commands config loaded: {len(self.commands)} commands, {len(self.aliases)} aliases, {len(self.groups)} groups")
                if old_commands_count > 0:
                    logging.info(f"Reloaded: was {old_commands_count} commands, now {len(self.commands)}")
            else:
                logging.warning(f"Commands config {self.config_path} not found, creating defaults")
                self.commands = DEFAULT_COMMANDS_CONFIG['commands']
                self.groups = DEFAULT_COMMANDS_CONFIG['groups']
                self._build_aliases()
                self.save_config()
                self.last_loaded_time = datetime.now()
        except Exception as e:
            logging.error(f"Error loading commands config: {e}")
            if not self.commands:
                self.commands = DEFAULT_COMMANDS_CONFIG['commands']
                self.groups = DEFAULT_COMMANDS_CONFIG['groups']
                self._build_aliases()
                self.last_loaded_time = datetime.now()

    def _build_aliases(self):
        """Build alias dictionary"""
        self.aliases = {}
        for cmd_name, cmd_info in self.commands.items():
            for alias in cmd_info.get('aliases', []):
                alias_lower = alias.lower()
                if alias_lower in self.aliases:
                    logging.warning(f"Alias '{alias}' already used by command '{self.aliases[alias_lower]}'")
                else:
                    self.aliases[alias_lower] = cmd_name

    def resolve_command(self, command_name: str) -> str:
        """Resolve alias to command name"""
        cmd_lower = command_name.lower()
        if cmd_lower in self.aliases:
            return self.aliases[cmd_lower]
        return cmd_lower

    def save_config(self):
        """Save config to file"""
        try:
            config = {'groups': self.groups, 'commands': self.commands}
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logging.info(f"Commands config saved to {self.config_path}")
        except Exception as e:
            logging.error(f"Error saving commands config: {e}")

    def get_user_groups(self, jid: str) -> set:
        user_groups = set()
        for group_name, members in self.groups.items():
            if jid in members:
                user_groups.add(group_name)
        return user_groups

    def check_command_access(self, command_name: str, user_jid: str) -> tuple[bool, bool, Optional[str]]:
        cmd_info = self.get_command_info(command_name)
        if not cmd_info:
            return False, False, None
        groups_only = cmd_info.get('groups_only', [])
        if not groups_only:
            return True, True, None
        user_groups = self.get_user_groups(user_jid)
        allowed_groups = set(groups_only)
        if user_groups & allowed_groups:
            return True, True, None
        return True, False, None

    def parse_command(self, text: str) -> Optional[tuple]:
        if not text.startswith('/'):
            return None
        parts = shlex.split(text[1:])
        if not parts:
            return None
        command_name = parts[0].lower()
        command_name = self.resolve_command(command_name)
        args = parts[1:] if len(parts) > 1 else []
        return command_name, args

    def get_command_info(self, command_name: str) -> Optional[dict]:
        return self.commands.get(command_name)

    def get_available_commands_for_user(self, user_jid: str) -> dict:
        available = {}
        for cmd_name, cmd_info in self.commands.items():
            exists, has_access, _ = self.check_command_access(cmd_name, user_jid)
            if exists and has_access:
                available[cmd_name] = cmd_info
        return available

    def get_help_text(self, user_jid: str = None) -> str:
        help_lines = [f"🤖 XMPP Bot v{__version__}", "", "Available commands:"]
        if user_jid:
            available_commands = self.get_available_commands_for_user(user_jid)
        else:
            available_commands = self.commands
        if not available_commands:
            help_lines.append("  No available commands")
        for cmd_name, cmd_info in sorted(available_commands.items()):
            desc = cmd_info.get('description', 'No description')
            args = cmd_info.get('args', [])
            aliases = cmd_info.get('aliases', [])
            groups_only = cmd_info.get('groups_only', [])
            
            cmd_names = [f"/{cmd_name}"] + [f"/{a}" for a in aliases]
            cmd_str = ", ".join(cmd_names)
            
            args_str = ""
            for arg in args:
                arg_name = arg.get('name', 'arg')
                if arg.get('required', True):
                    args_str += f" <{arg_name}>"
                else:
                    args_str += f" [{arg_name}]"
            
            access_info = ""
            if groups_only and user_jid:
                user_groups = self.get_user_groups(user_jid)
                allowed_groups = set(groups_only)
                if user_groups & allowed_groups:
                    access_info += f" 🔒 [groups: {', '.join(groups_only)}]"
            
            help_lines.append(f"  {cmd_str}{args_str} — {desc}{access_info}")
        return "\n".join(help_lines)

    async def execute_command(self, command_name: str, args: list, user_jid: str = None) -> str:
        if user_jid:
            command_exists, has_access, _ = self.check_command_access(command_name, user_jid)
            if not command_exists:
                return f"❌ Unknown command: /{command_name}\nUse /help for command list"
            if not has_access:
                logging.warning(f"User {user_jid} attempted forbidden command /{command_name}")
                return f"❌ Unknown command: /{command_name}\nUse /help for command list"
        cmd_info = self.get_command_info(command_name)
        if not cmd_info:
            return f"❌ Unknown command: /{command_name}\nUse /help for command list"
        if command_name == 'help':
            return self.get_help_text(user_jid)
        if command_name == 'ping':
            return "🏓 pong"
        if command_name == 'reload':
            return await self._handle_reload_command()
        if command_name == 'status':
            return "📊 Status unavailable"
        script_path = cmd_info.get('script')
        if not script_path:
            logging.error(f"Command /{command_name} not configured (no script path)")
            return f"❌ Command /{command_name} not configured"
        if not os.path.isabs(script_path):
            script_path = os.path.join(self.scripts_dir, script_path)
        if not os.path.exists(script_path):
            logging.error(f"Script not found: {script_path}")
            return "❌ Execution error (script not found)"
        cmd_args = [script_path]
        cmd_def = cmd_info.get('args', [])
        for i, arg_def in enumerate(cmd_def):
            if i < len(args):
                cmd_args.append(args[i])
            elif arg_def.get('required', True):
                arg_name = arg_def.get('name', f'arg{i+1}')
                return f"❌ Required argument missing: {arg_name}\nUsage: /{command_name} " + \
                       ' '.join([f"<{a.get('name', 'arg')}>" if a.get('required', True) else f"[{a.get('name', 'arg')}]" for a in cmd_def])
            elif 'default' in arg_def:
                cmd_args.append(str(arg_def['default']))
        try:
            logging.info(f"Executing command by {user_jid}: {' '.join(cmd_args)}")
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except asyncio.TimeoutError:
                process.kill()
                logging.error(f"Command timeout (30s): {' '.join(cmd_args)}")
                return "⏰ Command timed out"
            if process.returncode == 0:
                output = stdout.decode('utf-8', errors='replace').strip()
                logging.info(f"Command completed successfully (code {process.returncode})")
                if output:
                    log_output = output[:200] + "..." if len(output) > 200 else output
                    logging.debug(f"Command output: {log_output}")
                    return f"📊 Result:\n{output}"
                else:
                    return "✅ Command completed successfully"
            else:
                error_output = stderr.decode('utf-8', errors='replace').strip() if stderr else ""
                if error_output:
                    logging.error(f"Command error (code {process.returncode}): {error_output}")
                else:
                    logging.error(f"Command error (code {process.returncode})")
                return f"❌ Execution error (code {process.returncode})"
        except FileNotFoundError:
            logging.error(f"Failed to run script (FileNotFoundError): {script_path}")
            return "❌ Execution error (script not found)"
        except PermissionError as e:
            logging.error(f"Permission denied for script {script_path}: {e}")
            return "❌ Execution error (permission denied)"
        except Exception as e:
            logging.error(f"Exception executing command {command_name}: {type(e).__name__}: {e}")
            if logging.getLogger().level <= logging.DEBUG:
                traceback.print_exc()
            return "❌ Execution error (code 2)"

    async def _handle_reload_command(self) -> str:
        reload_results = []
        old_commands = set(self.commands.keys())
        old_groups = set(self.groups.keys())
        self.load_config()
        new_commands = set(self.commands.keys())
        new_groups = set(self.groups.keys())
        added_commands = new_commands - old_commands
        removed_commands = old_commands - new_commands
        added_groups = new_groups - old_groups
        removed_groups = old_groups - new_groups
        if added_commands:
            reload_results.append(f"✅ Commands added: {', '.join(sorted(added_commands))}")
        if removed_commands:
            reload_results.append(f"🗑️ Commands removed: {', '.join(sorted(removed_commands))}")
        if added_groups:
            reload_results.append(f"✅ Groups added: {', '.join(sorted(added_groups))}")
        if removed_groups:
            reload_results.append(f"🗑️ Groups removed: {', '.join(sorted(removed_groups))}")
        reload_results.append(f"📊 Total: {len(self.commands)} commands, {len(self.groups)} groups")
        reload_results.append(f"🕐 Config loaded: {self.last_loaded_time.strftime('%Y-%m-%d %H:%M:%S')}")
        return "🔄 Commands config reloaded!\n" + '\n'.join(reload_results)


class JabberSender(ClientXMPP):
    def __init__(self, jid, pwd, omemo, storage_path, storage, commands_config_path, main_config_path, scripts_dir, auto_reply_text=None, interactive=False, omemo_device_id=None):
        super().__init__(jid, pwd)
        self.use_omemo = omemo
        self.storage_path = storage_path
        self.storage = storage
        self.commands_config_path = commands_config_path
        self.main_config_path = main_config_path
        self.scripts_dir = scripts_dir
        self.auto_reply = auto_reply_text
        self.interactive = interactive
        self.active_chat = None
        self.start_time = datetime.now()
        self.omemo_device_id = omemo_device_id
        self.startup_params = {
            'jid': jid, 'password': pwd, 'omemo_enabled': omemo,
            'omemo_device_id': omemo_device_id, 'storage_file': storage_path,
            'commands_config': commands_config_path, 'main_config': main_config_path,
            'scripts_dir': scripts_dir, 'auto_reply': auto_reply_text, 'interactive': interactive
        }
        self.command_handler = CommandHandler(commands_config_path, scripts_dir)
        self.omemo = None
        self.shutdown_event = asyncio.Event()
        self.add_event_handler("session_start", self._start)
        self.add_event_handler("message", self._on_message)
        self.add_event_handler("failed_auth", self._on_failed_auth)
        self.add_event_handler("disconnected", self._on_disconnected)

    def get_status_text(self) -> str:
        status_lines = [f"📊 Bot Status v{__version__}", ""]
        status_lines.append("🔧 General:")
        status_lines.append(f"  JID: {self.startup_params['jid']}")
        status_lines.append(f"  Password: {mask_password(self.startup_params['password'])}")
        status_lines.append(f"  OMEMO: {'✅ Enabled' if self.use_omemo else '❌ Disabled'}")
        if self.startup_params['omemo_device_id']:
            status_lines.append(f"  OMEMO Device ID: {self.startup_params['omemo_device_id']}")
        status_lines.append(f"  Connected: {'✅ Yes' if self.is_connected() else '❌ No'}")
        status_lines.append("")
        status_lines.append("⏱️ Uptime:")
        status_lines.append(f"  Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        status_lines.append(f"  Running: {format_uptime(self.start_time)}")
        status_lines.append("")
        status_lines.append("📁 Configuration:")
        status_lines.append(f"  Main config: {self.main_config_path}")
        status_lines.append(f"  Commands config: {self.commands_config_path}")
        status_lines.append(f"  Scripts directory: {self.scripts_dir}")
        if self.command_handler.last_loaded_time:
            status_lines.append(f"  Commands loaded: {self.command_handler.last_loaded_time.strftime('%Y-%m-%d %H:%M:%S')}")
        status_lines.append("")
        status_lines.append("📈 Statistics:")
        status_lines.append(f"  Commands: {len(self.command_handler.commands)}")
        status_lines.append(f"  Aliases: {len(self.command_handler.aliases)}")
        status_lines.append(f"  Groups: {len(self.command_handler.groups)}")
        for group_name, members in sorted(self.command_handler.groups.items()):
            status_lines.append(f"  {group_name}: {len(members)} members")
        status_lines.append("")
        status_lines.append("💾 Storage:")
        status_lines.append(f"  File: {self.storage_path}")
        if os.path.exists(self.storage_path):
            file_size = os.path.getsize(self.storage_path)
            status_lines.append(f"  Size: {file_size:,} bytes")
            status_lines.append(f"  Records: {len(self.storage._data)}")
        else:
            status_lines.append(f"  Status: file not created")
        status_lines.append("")
        status_lines.append("📝 Logging:")
        level_name = logging.getLevelName(logging.getLogger().level)
        status_lines.append(f"  Level: {level_name}")
        status_lines.append("")
        status_lines.append("💬 Auto-reply:")
        if self.auto_reply:
            status_lines.append(f"  Text: {self.auto_reply[:50]}...")
        else:
            status_lines.append(f"  Status: disabled")
        return "\n".join(status_lines)

    def _on_failed_auth(self, event):
        logging.error("❌ Authentication failed!")
        self.disconnect()

    def _on_disconnected(self, event):
        if self.storage:
            try:
                self.storage.save_sync(self.storage_path)
            except:
                pass
        self.shutdown_event.set()

    async def _omemo_init(self):
        if self.omemo:
            await self.omemo.session_bind(self.boundjid.bare)
            if hasattr(self.omemo.plugin, 'announce_support'):
                try:
                    await self.omemo.plugin.announce_support()
                except:
                    pass

    def _start(self, e):
        self.send_presence()
        self.get_roster()
        if self.use_omemo and self.omemo:
            asyncio.ensure_future(self._omemo_init())
        if self.interactive:
            print(f"\n✅ Connected as {self.boundjid}")
            print(f"   Version: {__version__}")
            print("Waiting for messages... (Ctrl+C to exit)")
            print("Available commands: /help, /ping and others from config")

    def _on_message(self, msg):
        if msg['type'] not in ('chat', 'normal'):
            return
        sender = msg['from'].bare
        if 'xep_0333' in self.plugin:
            try:
                plugin = self.plugin['xep_0333']
                try:
                    plugin.send_marker(msg, marker='displayed')
                except TypeError:
                    marker = self.Message()
                    marker['to'] = msg['from']
                    marker['type'] = msg['type']
                    marker['displayed']['id'] = msg['id']
                    marker.send()
            except Exception:
                pass
        is_encrypted = False
        try:
            if self.omemo and self.omemo.is_encrypted(msg):
                is_encrypted = True
            elif msg.xml is not None:
                if msg.xml.find('{eu.siacs.conversations.axolotl}encrypted') is not None:
                    is_encrypted = True
                elif msg.xml.find('{urn:xmpp:omemo:2}encrypted') is not None:
                    is_encrypted = True
        except Exception as e:
            logging.debug(f"Encryption check error: {e}")
        if is_encrypted:
            asyncio.ensure_future(self._handle_encrypted_message(msg, sender))
            return
        body = msg.get('body', '')
        if body:
            asyncio.ensure_future(self._process_message(sender, body))

    async def _handle_encrypted_message(self, msg, sender):
        try:
            result = await self.omemo.decrypt_message(msg)
            body = None
            if isinstance(result, tuple):
                decrypted_msg, _ = result
                if decrypted_msg is not None:
                    if hasattr(decrypted_msg, 'get'):
                        body = decrypted_msg.get('body', '')
                    elif hasattr(decrypted_msg, 'body'):
                        body = decrypted_msg.body
                    elif isinstance(decrypted_msg, str):
                        body = decrypted_msg
            elif isinstance(result, str):
                body = result
            elif hasattr(result, 'get'):
                body = result.get('body', '')
            if body:
                await self._process_message(sender, body)
            else:
                logging.warning(f"Could not extract message body from {sender}")
        except Exception as e:
            logging.error(f"OMEMO decryption error from {sender}: {type(e).__name__}: {e}")
            if logging.getLogger().level <= logging.DEBUG:
                traceback.print_exc()

    async def _process_message(self, sender, body):
        print(f"\n📩 {sender}: {body}")
        user_groups = self.command_handler.get_user_groups(sender)
        if user_groups:
            logging.debug(f"User {sender} groups: {', '.join(sorted(user_groups))}")
        try:
            command = self.command_handler.parse_command(body)
        except Exception as e:
            logging.error(f"Command parse error from {sender}: {type(e).__name__}: {e}")
            command = None
        if command:
            command_name, args = command
            logging.info(f"Command from {sender}: /{command_name} {' '.join(args)}")
            try:
                if command_name == 'status':
                    command_exists, has_access, _ = self.command_handler.check_command_access(command_name, sender)
                    if not command_exists or not has_access:
                        response = f"❌ Unknown command: /{command_name}\nUse /help for command list"
                        if command_exists:
                            logging.warning(f"User {sender} attempted forbidden command /{command_name}")
                    else:
                        response = self.get_status_text()
                else:
                    response = await self.command_handler.execute_command(command_name, args, user_jid=sender)
                if command_name == 'reload' and response and '🔄' in response:
                    asyncio.ensure_future(self._full_reload())
            except Exception as e:
                logging.error(f"Critical error executing /{command_name} from {sender}: {type(e).__name__}: {e}")
                if logging.getLogger().level <= logging.DEBUG:
                    traceback.print_exc()
                response = "❌ Execution error (code 2)"
            if response:
                await self.send_text(sender, response)
                log_response = response[:100] + "..." if len(response) > 100 else response
                print(f"🤖 Reply to {sender}: {log_response}")
        elif self.auto_reply:
            await self._auto_reply(sender)

    async def _auto_reply(self, to):
        await asyncio.sleep(1)
        await self.send_text(to, self.auto_reply)
        print(f"📤 Auto-reply to {to}: {self.auto_reply}")

    async def _full_reload(self):
        logging.info("🔄 Starting full config reload...")
        validation_errors = []
        try:
            if not os.path.exists(self.main_config_path):
                validation_errors.append(f"❌ Main config not found: {self.main_config_path}")
            else:
                with open(self.main_config_path, 'r', encoding='utf-8') as f:
                    main_config = json.load(f)
        except json.JSONDecodeError as e:
            validation_errors.append(f"❌ Main config parse error: {e}")
        except Exception as e:
            validation_errors.append(f"❌ Main config validation error: {e}")

        commands_config_path = main_config.get('commands_config', self.commands_config_path) if 'main_config' in dir() else self.commands_config_path
        try:
            if not os.path.exists(commands_config_path):
                validation_errors.append(f"❌ Commands config not found: {commands_config_path}")
            else:
                with open(commands_config_path, 'r', encoding='utf-8') as f:
                    json.load(f)
        except json.JSONDecodeError as e:
            validation_errors.append(f"❌ Commands config parse error: {e}")
        except Exception as e:
            validation_errors.append(f"❌ Commands config validation error: {e}")

        if validation_errors:
            error_message = "❌ Configuration validation errors:\n" + "\n".join(validation_errors)
            logging.error(error_message)
            if self.active_chat:
                await self.send_text(self.active_chat, error_message)
            return

        try:
            new_commands_config = main_config.get('commands_config', self.commands_config_path)
            if new_commands_config != self.commands_config_path:
                self.commands_config_path = new_commands_config
                self.command_handler = CommandHandler(new_commands_config, self.scripts_dir)
            else:
                self.command_handler.load_config()
            new_scripts_dir = main_config.get('scripts_dir', SCRIPTS_DIR)
            if new_scripts_dir != self.scripts_dir:
                self.scripts_dir = new_scripts_dir
                self.command_handler.scripts_dir = new_scripts_dir
                self.startup_params['scripts_dir'] = new_scripts_dir
                logging.info(f"🔄 Scripts dir updated: {self.scripts_dir}")
            new_auto_reply = main_config.get('auto_reply')
            if new_auto_reply != self.auto_reply:
                self.auto_reply = new_auto_reply
                self.startup_params['auto_reply'] = new_auto_reply
                logging.info(f"🔄 Auto-reply updated: {self.auto_reply}")
            log_level_str = main_config.get('log_level', 'INFO').upper()
            log_level = getattr(logging, log_level_str, logging.INFO)
            logging.getLogger().setLevel(log_level)
            logging.info(f"🔄 Log level: {log_level_str}")
            if self.use_omemo and self.storage:
                try:
                    self.storage.save_sync(self.storage_path)
                except Exception as e:
                    logging.error(f"Error saving OMEMO during reload: {e}")
            logging.info("✅ Full config reload completed")
            if self.active_chat:
                await self.send_text(self.active_chat, "✅ Configuration reloaded")
        except Exception as e:
            logging.error(f"❌ Error applying config: {e}")
            if self.active_chat:
                await self.send_text(self.active_chat, f"❌ Reload error: {e}")

    async def shutdown(self):
        if not self.shutdown_event.is_set():
            print("\nShutting down...")
            if self.storage:
                try:
                    self.storage.save_sync(self.storage_path)
                except:
                    pass
            self.shutdown_event.set()
            if self.is_connected():
                self.disconnect()

    async def send_omemo(self, to, body):
        if not self.omemo:
            return False
        msg = self.make_message(mto=to, mbody=body, mtype='chat')
        try:
            sm = await self.omemo.get_session_manager()
            jid_obj = JID(to)
            device_ids = set()
            for ns in ['urn:xmpp:omemo:2', 'eu.siacs.conversations.axolotl']:
                node = f'{ns}:devices' if ns == 'urn:xmpp:omemo:2' else f'{ns}.devicelist'
                iq = self.Iq()
                iq['type'] = 'get'
                iq['to'] = to
                iq['pubsub']['items']['node'] = node
                try:
                    resp = await iq.send()
                    for d in resp['pubsub']['items'].xml.findall('.//{*}device'):
                        device_ids.add(int(d.get('id')))
                    if device_ids:
                        await sm.update_device_list(ns, jid_obj, {did: None for did in device_ids})
                except Exception as e:
                    logging.debug(f"Device list {ns}: {e}")
            if not device_ids:
                logging.warning(f"No OMEMO devices for {to}")
                return False
            result = await self.omemo.encrypt_message(msg, {jid_obj})

            def send_stanza(stanza):
                if hasattr(stanza, 'send'):
                    stanza.send()
                    return True
                return False

            if isinstance(result, tuple) and len(result) > 0:
                messages = result[0]
                if messages is not None:
                    if send_stanza(messages):
                        return True
                    try:
                        for stanza in messages.values():
                            if send_stanza(stanza):
                                return True
                    except AttributeError:
                        pass
            elif send_stanza(result):
                return True
            return False
        except Exception as e:
            logging.error(f"OMEMO error: {e}")
            if logging.getLogger().level <= logging.DEBUG:
                traceback.print_exc()
        return False

    async def send_text(self, to, body):
        if self.use_omemo and await self.send_omemo(to, body):
            print(f"🔐 OMEMO → {to}: {body[:50]}...")
            return True
        self.make_message(mto=to, mbody=body, mtype='chat').send()
        print(f"📤 {to}: {body[:50]}...")
        return True

    async def upload(self, path, to):
        filename = Path(path).name
        size = Path(path).stat().st_size
        mt = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        with open(path, 'rb') as f:
            url = await self.plugin['xep_0363'].upload_file(filename=filename, size=size, content_type=mt, input_file=f)
        return url

    async def send_image(self, to, path, cap=None):
        url = await self.upload(path, to)
        if not url:
            return False
        if self.use_omemo:
            if cap:
                await self.send_omemo(to, cap)
            msg = self.make_message(mto=to, mtype='chat')
            msg['body'] = url
            msg['oob']['url'] = url
            try:
                result = await self.omemo.encrypt_message(msg, {JID(to)})
                def send_stanza(stanza):
                    if hasattr(stanza, 'send'):
                        stanza['oob']['url'] = url
                        stanza.send()
                        return True
                    return False
                if isinstance(result, tuple) and len(result) > 0:
                    messages = result[0]
                    if messages is not None:
                        if send_stanza(messages):
                            print(f"🔐 Image → {to}")
                            return True
                        try:
                            for stanza in messages.values():
                                if send_stanza(stanza):
                                    print(f"🔐 Image → {to}")
                                    return True
                        except AttributeError:
                            pass
                elif send_stanza(result):
                    print(f"🔐 Image → {to}")
                    return True
            except Exception as e:
                logging.error(f"OMEMO OOB: {e}")
                return False
        msg = self.make_message(mto=to, mtype='chat')
        msg['body'] = f"{cap}\n{url}" if cap else url
        msg['oob']['url'] = url
        msg.send()
        print(f"🖼️ Image → {to}")
        return True

    async def send_base64(self, to, data, cap=None, fn=None):
        tmp = None
        try:
            if ',' in data:
                data = data.split(',', 1)[1]
            img = base64.b64decode(data)
            fn = fn or f"img_{datetime.now():%Y%m%d_%H%M%S}.png"
            tmp = os.path.join(tempfile.gettempdir(), fn)
            with open(tmp, 'wb') as f:
                f.write(img)
            return await self.send_image(to, tmp, cap)
        except Exception as e:
            logging.error(f"Base64 error: {e}")
            return False
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

    async def send_stdin(self, to, cap=None):
        data = ''.join(sys.stdin.read().split())
        return await self.send_base64(to, data, cap) if data else False


async def main():
    main_config = load_main_config(CONFIG_FILE)
    p = argparse.ArgumentParser(description=f'XMPP bot v{__version__} with command system from config')
    p.add_argument('-j', '--jid', default=main_config['jid'], help='Sender JID')
    p.add_argument('-p', '--password', default=main_config['password'], help='Password')
    p.add_argument('-v', '--version', action='version', version=f'%(prog)s {__version__}')
    p.add_argument('--omemo-device', type=int, default=main_config['omemo_device_id'], help='OMEMO device_id')
    p.add_argument('-t', '--to', help='Recipient JID')
    p.add_argument('-m', '--message', help='Message text')
    g = p.add_mutually_exclusive_group()
    g.add_argument('-i', '--image', help='Image path')
    g.add_argument('-b', '--base64', help='Base64 string')
    g.add_argument('--base64-file', help='Base64 file')
    g.add_argument('-s', '--stdin', action='store_true', help='Read base64 from stdin')
    p.add_argument('-N', '--no-omemo', action='store_true', help='Disable OMEMO')
    p.add_argument('--listen', action='store_true', help='Listen mode')
    p.add_argument('--auto-reply', nargs='?', const=False, default=main_config.get('auto_reply'), help='Auto-reply text')
    p.add_argument('-c', '--config', default=main_config.get('commands_config', CONFIG_FILE_BOT), help='Commands config path')
    p.add_argument('-d', '--debug', action='store_true', help='Debug mode')
    args = p.parse_args()

    log_level = logging.DEBUG if args.debug else getattr(logging, main_config.get('log_level', 'INFO').upper(), logging.INFO)
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

    if not args.jid or not args.password:
        p.error("JID and password must be specified in arguments or in /etc/xmpp_bot/config.json")

    is_one_shot = bool(args.to and (args.message or any([args.image, args.base64, args.base64_file, args.stdin])))
    is_interactive = args.listen or not is_one_shot

    if not is_one_shot and not is_interactive:
        p.error("Specify -t and -m to send or --listen to receive")

    use_omemo = not args.no_omemo and main_config.get('omemo_enabled', True)
    auto_reply_text = None
    if args.auto_reply is not False:
        if isinstance(args.auto_reply, str) and args.auto_reply:
            auto_reply_text = args.auto_reply
        elif main_config.get('auto_reply'):
            auto_reply_text = main_config['auto_reply']

    storage_file = main_config.get('storage_file', STORAGE_FILE)
    commands_config_file = args.config
    scripts_dir = main_config.get('scripts_dir', SCRIPTS_DIR)

    storage = DictStorage()
    if use_omemo:
        storage.load_sync(storage_file)

    x = JabberSender(
        jid=args.jid, pwd=args.password, omemo=use_omemo,
        storage_path=storage_file, storage=storage,
        commands_config_path=commands_config_file,
        main_config_path=CONFIG_FILE,
        scripts_dir=scripts_dir,
        auto_reply_text=auto_reply_text,
        interactive=is_interactive,
        omemo_device_id=args.omemo_device
    )

    x.register_plugin('xep_0030')
    x.register_plugin('xep_0199')
    x.register_plugin('xep_0363')
    x.register_plugin('xep_0066')
    x.register_plugin('xep_0334')

    if use_omemo:
        try:
            if 'xep_0060' not in x.plugin:
                x.register_plugin('xep_0060')
            _storage = storage
            class PatchedXEP0384(XEP_0384):
                name = 'xep_0384'
                dependencies = {'xep_0060'}
                @property
                def storage(self):
                    return _storage
                def _btbv_enabled(self) -> bool:
                    return True
                async def _prompt_manual_trust(self, jid, device_id, fingerprint):
                    await self.trust(fingerprint, jid, device_id, TrustLevel.TRUSTED)
            plugin_instance = PatchedXEP0384(x, {})
            x.plugin._plugins['xep_0384'] = plugin_instance
            x.plugin['xep_0030'].add_feature('urn:xmpp:omemo:2')
            x.plugin['xep_0030'].add_feature('eu.siacs.conversations.axolotl')
            if args.omemo_device and hasattr(plugin_instance, 'device_id'):
                plugin_instance.device_id = args.omemo_device
            x.omemo = WorkingOMEMO(x)
        except Exception as e:
            logging.error(f"OMEMO error: {e}")
            if args.debug:
                traceback.print_exc()
            x.use_omemo = False

    x.register_plugin('xep_0333')

    loop = asyncio.get_running_loop()
    async def signal_handler():
        await x.shutdown()
    async def reload_signal_handler():
        logging.info("📡 SIGHUP received - reloading config")
        await x._full_reload()
    def handle_signal():
        asyncio.ensure_future(signal_handler())
    def handle_reload_signal():
        asyncio.ensure_future(reload_signal_handler())
    try:
        loop.add_signal_handler(signal.SIGINT, handle_signal)
        loop.add_signal_handler(signal.SIGTERM, handle_signal)
        loop.add_signal_handler(signal.SIGHUP, handle_reload_signal)
    except NotImplementedError:
        pass

    try:
        x.connect()
        for _ in range(20):
            if x.authenticated:
                break
            await asyncio.sleep(0.5)
        if not x.authenticated:
            logging.error("❌ Authentication timeout")
            return 1
        if is_one_shot:
            ok = False
            if args.image:
                ok = await x.send_image(args.to, args.image, args.message)
            elif args.base64:
                ok = await x.send_base64(args.to, args.base64, args.message)
            elif args.base64_file:
                data = Path(args.base64_file).read_text().strip()
                ok = await x.send_base64(args.to, data, args.message)
            elif args.stdin:
                ok = await x.send_stdin(args.to, args.message)
            elif args.message:
                ok = await x.send_text(args.to, args.message)
            await asyncio.sleep(3)
            if use_omemo:
                x.storage.save_sync(storage_file)
            x.disconnect()
            print("✅ Success!" if ok else "❌ Error")
            return 0 if ok else 1
        if args.to:
            x.active_chat = args.to
            print(f"💬 Active chat: {args.to}")
        await x.shutdown_event.wait()
        if use_omemo:
            try:
                x.storage.save_sync(storage_file)
            except:
                pass
        return 0
    except KeyboardInterrupt:
        await x.shutdown()
        return 1
    except Exception as e:
        logging.error(f"❌ Error: {e}")
        if args.debug:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
