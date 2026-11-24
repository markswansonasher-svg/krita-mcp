#!/usr/bin/env python3
"""
One-step installer for Krita MCP on Windows, macOS and Linux.

    python install.py            (Windows: or double-click install.cmd)
    python3 install.py           (macOS / Linux)

It does four things:
  1. copies the Krita plugin into Krita's pykrita folder
  2. turns the plugin on in Krita's settings (kritarc)
  3. makes a private Python environment (.venv) next to this file and installs the server's
     packages into it (mcp, numpy, scipy, pillow) - nothing is installed system-wide
  4. registers the server with Claude Code if the `claude` command is available, and prints the
     snippet for Claude Desktop / other MCP clients

Options:
  --plugin-only     only steps 1-2 (e.g. you run the server with uv instead)
  --no-register     don't run `claude mcp add`
  --flatpak         Krita is the Flatpak build (found automatically when it is installed)
  --dry-run         show what would happen, change nothing

Needs Python 3.10+ (only the standard library is used here). Close Krita first: it rewrites its
settings file when it quits.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_SRC = os.path.join(HERE, "plugin")
VENV = os.path.join(HERE, ".venv")
HOME = os.path.expanduser("~")
FLATPAK_APP = os.path.join(HOME, ".var", "app", "org.kde.krita")


def krita_dirs(platform=sys.platform, flatpak=False):
    """(pykrita folder, kritarc file) for this OS."""
    if platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
        local = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
        return os.path.join(appdata, "krita", "pykrita"), os.path.join(local, "kritarc")
    if platform == "darwin":
        return (os.path.join(HOME, "Library", "Application Support", "krita", "pykrita"),
                os.path.join(HOME, "Library", "Preferences", "kritarc"))
    if flatpak:
        return (os.path.join(FLATPAK_APP, "data", "krita", "pykrita"),
                os.path.join(FLATPAK_APP, "config", "kritarc"))
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
    return os.path.join(data, "krita", "pykrita"), os.path.join(config, "kritarc")


def krita_running():
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq krita.exe", "/NH"],
                                 capture_output=True, text=True).stdout
            return "krita.exe" in out.lower()
        return subprocess.run(["pgrep", "-ix", "krita"], capture_output=True).returncode == 0
    except OSError:
        return False                      # can't tell; carry on


def install_plugin(pykrita, dry):
    dest = os.path.join(pykrita, "krita_mcp")
    print(f"  plugin  -> {dest}")
    if dry:
        return
    os.makedirs(pykrita, exist_ok=True)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(os.path.join(PLUGIN_SRC, "krita_mcp"), dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(os.path.join(PLUGIN_SRC, "kritapykrita_krita_mcp.desktop"), pykrita)


def enable_plugin(kritarc, dry):
    """[python] enable_krita_mcp=true, keeping everything else in the file as it is."""
    print(f"  enable  -> {kritarc}")
    lines = []
    if os.path.exists(kritarc):
        with open(kritarc, encoding="utf-8", errors="surrogateescape") as f:
            lines = f.read().splitlines()
    out, in_python, done, has_section = [], False, False, False
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_python and not done:
                out.append("enable_krita_mcp=true")
                done = True
            in_python = s == "[python]"
            has_section = has_section or in_python
        elif in_python and s.startswith("enable_krita_mcp="):
            line, done = "enable_krita_mcp=true", True
        out.append(line)
    if in_python and not done:
        out.append("enable_krita_mcp=true")
    if not has_section:
        out += ["", "[python]", "enable_krita_mcp=true"]
    if dry:
        return
    os.makedirs(os.path.dirname(kritarc), exist_ok=True)
    if os.path.exists(kritarc):
        shutil.copy2(kritarc, kritarc + ".before-krita-mcp")
    with open(kritarc, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write("\n".join(out) + "\n")


def venv_python():
    sub = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    return os.path.join(VENV, *sub)


def install_server(dry):
    py = venv_python()
    print(f"  server  -> {VENV} (mcp, numpy, scipy, pillow)")
    if dry:
        return py
    if not os.path.exists(py):
        try:
            venv.EnvBuilder(with_pip=True).create(VENV)
        except Exception as e:                       # Debian/Ubuntu without python3-venv
            sys.exit(f"Couldn't create a virtual environment ({e}).\n"
                     "On Debian/Ubuntu install it with:  sudo apt install python3-venv")
    req = os.path.join(HERE, "requirements.txt")
    subprocess.run([py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", req], check=True)
    # quick self-check: the server imports cleanly
    subprocess.run([py, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import server; "
                              "print('  server imports OK')", HERE], check=True, cwd=HERE)
    return py


def register(py, dry, enabled):
    server = os.path.join(HERE, "server.py")
    claude = shutil.which("claude")
    if enabled and claude:
        cmd = [claude, "mcp", "add", "krita", "-s", "user", "--", py, server]
        print("  claude  -> " + " ".join(f'"{c}"' if " " in c else c for c in cmd[1:]))
        if not dry:
            subprocess.run([claude, "mcp", "remove", "krita", "-s", "user"], capture_output=True)
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print("    (couldn't register automatically: " + (r.stderr or r.stdout).strip() + ")")
    snippet = {"mcpServers": {"krita": {"command": py, "args": [server]}}}
    print("\nFor Claude Desktop or another MCP client, add this to its config file:\n")
    print(json.dumps(snippet, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Install Krita MCP")
    ap.add_argument("--plugin-only", action="store_true")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--flatpak", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if sys.version_info < (3, 10):
        sys.exit("Krita MCP needs Python 3.10 or newer (this is %d.%d)." % sys.version_info[:2])
    flatpak = a.flatpak or (sys.platform.startswith("linux") and os.path.isdir(FLATPAK_APP)
                            and not os.path.isdir(krita_dirs()[0]))
    if krita_running() and not a.dry_run:
        sys.exit("Krita is running. Close it, then run this again.")

    pykrita, kritarc = krita_dirs(flatpak=flatpak)
    print("Installing Krita MCP" + (" (Flatpak Krita)" if flatpak else "") + (" [dry run]" if a.dry_run else ""))
    install_plugin(pykrita, a.dry_run)
    enable_plugin(kritarc, a.dry_run)
    if a.plugin_only:
        print("\nDone. Run the server with:  uv run " + os.path.join(HERE, "server.py"))
    else:
        py = install_server(a.dry_run)
        register(py, a.dry_run, not a.no_register)
    print("\nDone. Start Krita; the bridge listens on 127.0.0.1:9877 "
          "(check it with Tools > Scripts > Krita MCP (Claude): status).")
    if not a.plugin_only:
        print("Restart Claude so it loads the krita tools.")


if __name__ == "__main__":
    main()
