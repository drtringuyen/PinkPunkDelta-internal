"""What this PC needs so the iPad reaches it: detected without admin rights, set up with one
Windows prompt. No bpy, runs in threads.

Set up: the folder shared for the user's own account only, and two firewall rules for private
networks and the local subnet. Nothing else is opened; Remove takes it all away again."""
import base64
import ctypes
import json
import os
import subprocess
import sys
import threading
import time

SHARE = "PPD_Procreate"
RULE_LINK = "PPD LiveLink"          # the add-on version's rule: Blender, the link's port
RULE_FILES = "PPD LiveLink files"   # the shared folder, TCP 445

_CHECK = r"""
$ErrorActionPreference = 'SilentlyContinue'; $ProgressPreference = 'SilentlyContinue'
$up = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' })
$nets = @(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } | ForEach-Object {
  $c = $_; $a = $up | Where-Object { $_.ifIndex -eq $c.InterfaceIndex }
  @{ ip = @($c.IPv4Address)[0].IPAddress; name = $c.InterfaceAlias; hardware = [bool]$a.HardwareInterface
     category = [string](Get-NetConnectionProfile -InterfaceIndex $c.InterfaceIndex).NetworkCategory } })
$rules = @(@(Get-NetFirewallRule -DisplayName 'PPD LiveLink*') + @(Get-NetFirewallRule -Name 'FPS-SMB-In-TCP*') | Where-Object { [string]$_.Enabled -eq 'True' -and [string]$_.Action -eq 'Allow' } | ForEach-Object {
  @{ name = $_.DisplayName; program = [string]($_ | Get-NetFirewallApplicationFilter).Program
     port = [string]($_ | Get-NetFirewallPortFilter).LocalPort; profile = [string]$_.Profile } })
$share = Get-SmbShare -Name '%SHARE%'
@{ nets = $nets; rules = $rules; share = [string]$share.Path
   server = [string](Get-Service LanmanServer).Status
   user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
   connected = @(Get-NetTCPConnection -LocalPort 445 -State Established | Where-Object { $_.RemoteAddress -notmatch '^(127\.|::1)' -and $_.RemoteAddress -ne $_.LocalAddress }).Count
} | ConvertTo-Json -Depth 4 -Compress
"""

_SETUP = r"""
$ErrorActionPreference = 'Stop'
try {
  Write-Host 'PPD LiveLink: setting up this PC for the iPad'
  $svc = Get-Service LanmanServer
  if ($svc.StartType -eq 'Disabled') { Set-Service LanmanServer -StartupType Automatic }
  if ($svc.Status -ne 'Running') { Start-Service LanmanServer }
  New-Item -ItemType Directory -Force -Path %FOLDER% | Out-Null
  $s = Get-SmbShare -Name %SHARE% -ErrorAction SilentlyContinue
  if ($s -and $s.Path -ne %FOLDER%) { throw ('Another folder is already shared as ' + %SHARE% + ': ' + $s.Path) }
  if (-not $s) { New-SmbShare -Name %SHARE% -Path %FOLDER% -FullAccess %USER% | Out-Null }
  foreach ($n in %RULE%, %RULE_FILES%) { Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
  New-NetFirewallRule -DisplayName %RULE% -Direction Inbound -Action Allow -Protocol TCP -LocalPort %PORT% -Program %PROGRAM% -Profile Private -RemoteAddress LocalSubnet | Out-Null
  New-NetFirewallRule -DisplayName %RULE_FILES% -Direction Inbound -Action Allow -Protocol TCP -LocalPort 445 -Profile Private -RemoteAddress LocalSubnet | Out-Null
} catch { Write-Host ''; Write-Host $_ -ForegroundColor Red; Read-Host 'Press Enter to close' }
"""

_REMOVE = r"""
try {
  $s = Get-SmbShare -Name %SHARE% -ErrorAction SilentlyContinue
  if ($s -and $s.Path -eq %FOLDER%) { Remove-SmbShare -Name %SHARE% -Force }
  foreach ($n in %RULE%, %RULE_FILES%) { Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue | Remove-NetFirewallRule }
} catch { Write-Host $_ -ForegroundColor Red; Read-Host 'Press Enter to close' }
"""


def quote(text):
    """A PowerShell literal: nothing in it is ever read as code."""
    for c in "\u2018\u2019\u201a\u201b":        # PowerShell takes these as quotes too
        text = text.replace(c, c * 2)
    return "'" + text.replace("'", "''") + "'"


def rule_name(version):
    return f"{RULE_LINK} (Blender {version})"


def fill(script, **values):
    for k, v in values.items():
        script = script.replace(f"%{k}%", v if k == "PORT" else quote(v))
    return script


def _encoded(script):
    return base64.b64encode(script.encode("utf-16-le")).decode()


def _powershell():
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                        "WindowsPowerShell", "v1.0", "powershell.exe")


def supported():
    return sys.platform == "win32"


def detect():
    r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        _encoded(_CHECK.replace("%SHARE%", SHARE))],
                       capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(r.stdout.decode("utf-8", "replace").strip())


def evaluate(d, folder, program, port, ip=""):
    """The checks (key, ok, text) of a detection, and the network the iPad must use."""
    nets = d.get("nets") or []
    nets = [nets] if isinstance(nets, dict) else nets
    net = next((n for n in nets if n["ip"] == ip), None) or \
        next((n for n in nets if n["hardware"]), None) or (nets[0] if nets else None)
    rules = d.get("rules") or []
    rules = [rules] if isinstance(rules, dict) else rules

    def private(r):
        return r["profile"] == "Any" or "Private" in r["profile"]

    link = any(r["port"] == str(port) and private(r) and
               os.path.normcase(r["program"]) == os.path.normcase(program) for r in rules)
    files = any(r["port"] == "445" and private(r) for r in rules)
    shared = bool(d.get("share")) and os.path.normcase(os.path.normpath(d["share"])) == \
        os.path.normcase(os.path.normpath(folder))
    other = bool(d.get("share")) and not shared
    checks = [
        ("net", net is not None, f"Network {net['name']}, {net['ip']}" if net
         else "No network connection"),
        ("private", bool(net) and net["category"] == "Private",
         "Network is set to Private" if net and net["category"] == "Private"
         else "Network is not set to Private in Windows"),
        ("service", d.get("server") == "Running", "Windows file sharing runs"
         if d.get("server") == "Running" else "Windows file sharing is off"),
        ("share", shared, f"{folder} is shared" if shared else
         (f"{SHARE} is another folder: {d['share']}" if other else f"{folder} is not shared yet")),
        ("link", link, "Firewall lets the iPad page through" if link
         else "Firewall blocks the iPad page"),
        ("files", files, "Firewall lets the folder through" if files
         else "Firewall rule for the folder is missing"),
    ]
    return checks, (net["ip"] if net else "")


def elevate(script):
    """Run in an admin PowerShell - Windows asks the user. False = they said no."""
    r = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", _powershell(), "-NoProfile -EncodedCommand " + _encoded(script), None, 1)
    return r > 32


class Monitor:
    """Detects in a thread; the panel and the page read what it found."""

    def __init__(self):
        self.checks, self.ip, self.user, self.error = [], "", "", ""
        self.connected = False      # some device has been in the shared folder
        self.busy = False
        self.changed = False        # the panel should redraw
        self.lock = threading.Lock()
        self.until = 0.0            # look again every few seconds until then

    @property
    def ready(self):
        return bool(self.checks) and all(ok for _k, ok, _t in self.checks)

    @property
    def login(self):
        return self.user.split("\\")[-1]

    def start(self, folder, program, port, ip="", follow=0.0):
        if not supported():
            return
        self.until = max(self.until, time.time() + follow)
        with self.lock:
            if self.busy:
                return
            self.busy = True
        threading.Thread(target=self._run, args=(folder, program, port, ip), daemon=True).start()

    def _run(self, *args):
        try:
            while True:
                try:
                    d = detect()
                    self.checks, self.ip = evaluate(d, *args)
                    self.user, self.error = d.get("user") or "", ""
                    self.connected = self.connected or bool(d.get("connected"))
                except Exception as e:
                    self.error = f"Could not check this PC: {e}"
                self.changed = True
                if self.ready or time.time() > self.until:
                    break
                time.sleep(3)
        finally:
            self.busy = False
            self.changed = True
