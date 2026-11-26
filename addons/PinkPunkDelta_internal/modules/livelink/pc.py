"""What this PC needs so the iPad reaches it: detected without admin rights, set up with one
Windows prompt. No bpy, runs in threads.

Set up: the folder shared for the user's own account only, and two firewall rules for private
networks and the local subnet. Nothing else is opened; Remove takes it all away again.

The iPad account (ppdipad): a local Windows account in no group, so it cannot sign in at the
PC, allowed into PPD_Procreate and blocked from every other share. The iPad logs in with it -
a PIN never works over the network, and a Microsoft or company account often cannot."""
import base64
import ctypes
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time

SHARE = "PPD_Procreate"
RULE_LINK = "PPD LiveLink"          # the add-on version's rule: Blender, the link's port
RULE_FILES = "PPD LiveLink files"   # the shared folder, TCP 445
ACCOUNT = "ppdipad"
ACCOUNT_NOTE = "iPad access to PPD_Procreate"   # marks the accounts made here

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
$acc = @{ name = %ACCOUNT%; exists = $false }
$u = Get-LocalUser -Name %ACCOUNT%
if ($u) {
  $acc.exists = $true; $acc.enabled = [bool]$u.Enabled; $acc.ours = $u.Description -eq '%NOTE%'
  try {   # may need admin rights: then it stays unknown
    $a = @(Get-SmbShareAccess -Name '%SHARE%' -ErrorAction Stop | Where-Object { $_.AccountName -like ('*\' + %ACCOUNT%) -and [string]$_.AccessControlType -eq 'Allow' })
    $acc.access = $a.Count -gt 0
  } catch {}
}
@{ nets = $nets; rules = $rules; share = [string]$share.Path; account = $acc
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

_ACCOUNT = r"""
$file = %PWFILE%
try {
  $ErrorActionPreference = 'Stop'
  Write-Host 'PPD LiveLink: the iPad account'
  $name = %ACCOUNT%
  $pw = ConvertTo-SecureString ([IO.File]::ReadAllText($file)) -AsPlainText -Force
  Remove-Item -LiteralPath $file -Force
  if (-not (Get-SmbShare -Name %SHARE% -ErrorAction SilentlyContinue)) { throw 'PPD_Procreate is not shared yet: press Set Up This PC first' }
  $u = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
  if ($u -and $u.Description -ne %NOTE%) { throw ($name + ' is an account PPD did not make. Pick another name.') }
  if ($u) { Set-LocalUser -Name $name -Password $pw; Enable-LocalUser -Name $name }
  else { New-LocalUser -Name $name -Password $pw -FullName 'PPD iPad' -Description %NOTE% -PasswordNeverExpires -AccountNeverExpires -UserMayNotChangePassword | Out-Null }
  $acct = "$env:COMPUTERNAME\$name"
  foreach ($s in Get-SmbShare | Where-Object { -not $_.Special -and $_.Name -notin %SHARE%, 'print$' -and $_.ShareType -eq 'FileSystemDirectory' }) {
    Block-SmbShareAccess -Name $s.Name -AccountName $acct -Force | Out-Null
  }
  Grant-SmbShareAccess -Name %SHARE% -AccountName $acct -AccessRight Change -Force | Out-Null
  & icacls.exe %FOLDER% /grant ($acct + ':(OI)(CI)M') | Out-Null
} catch { Write-Host ''; Write-Host $_ -ForegroundColor Red; Read-Host 'Press Enter to close' }
finally { if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force } }
"""

_ACCOUNT_TERMINAL = r"""
$result = %RESULT%
try {
  $ErrorActionPreference = 'Stop'
  $name = %ACCOUNT%
  Write-Host "PPD LiveLink: the iPad account $name on $env:COMPUTERNAME" -ForegroundColor Cyan
  Write-Host 'The iPad logs in with it (Registered User). It only opens PPD_Procreate and cannot sign in at this PC.'
  if (-not (Get-SmbShare -Name %SHARE% -ErrorAction SilentlyContinue)) { throw 'PPD_Procreate is not shared yet: press Set Up This PC in Blender first' }
  $u = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
  if ($u -and $u.Description -ne %NOTE%) { throw ($name + ' is an account PPD did not make. Pick another name in Blender.') }
  if ($u) { Write-Host "$name exists: this gives it a new password. Close the window to cancel." -ForegroundColor Yellow }
  while ($true) {
    $p1 = Read-Host 'Password (10 or more characters)' -AsSecureString
    $p2 = Read-Host 'Again' -AsSecureString
    $c1 = (New-Object System.Net.NetworkCredential('', $p1)).Password
    $c2 = (New-Object System.Net.NetworkCredential('', $p2)).Password
    if ($c1.Length -lt 10) { Write-Host 'Too short. Try again.' -ForegroundColor Yellow; continue }
    if ($c1 -ceq $c2) { break }
    Write-Host 'The two did not match. Try again.' -ForegroundColor Yellow
  }
  if ($u) { Set-LocalUser -Name $name -Password $p1; Enable-LocalUser -Name $name }
  else { New-LocalUser -Name $name -Password $p1 -FullName 'PPD iPad' -Description %NOTE% -PasswordNeverExpires -AccountNeverExpires -UserMayNotChangePassword | Out-Null }
  $acct = "$env:COMPUTERNAME\$name"
  foreach ($s in Get-SmbShare | Where-Object { -not $_.Special -and $_.Name -notin %SHARE%, 'print$' -and $_.ShareType -eq 'FileSystemDirectory' }) {
    Block-SmbShareAccess -Name $s.Name -AccountName $acct -Force | Out-Null
  }
  Grant-SmbShareAccess -Name %SHARE% -AccountName $acct -AccessRight Change -Force | Out-Null
  & icacls.exe %FOLDER% /grant ($acct + ':(OI)(CI)M') | Out-Null
  [IO.File]::WriteAllText($result, $c1)       # Blender shows it on the LiveLink page, then deletes this
  Write-Host ''
  Write-Host "Done. On the iPad: Registered User, name $name and this password." -ForegroundColor Green
  Write-Host 'Blender shows both on the LiveLink page with Copy buttons.'
} catch { Write-Host ''; Write-Host $_ -ForegroundColor Red }
Read-Host 'Press Enter to close'
"""

_ACCOUNT_REMOVE = r"""
try {
  $u = Get-LocalUser -Name %ACCOUNT% -ErrorAction SilentlyContinue
  if ($u -and $u.Description -eq %NOTE%) { Remove-LocalUser -Name %ACCOUNT% }
} catch { Write-Host $_ -ForegroundColor Red; Read-Host 'Press Enter to close' }
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


def detect(account=ACCOUNT):
    script = _CHECK.replace("%SHARE%", SHARE).replace("%NOTE%", ACCOUNT_NOTE) \
        .replace("%ACCOUNT%", quote(account))
    r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        _encoded(script)],
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
    acc = d.get("account")
    if isinstance(acc, dict) and acc.get("name"):
        n = acc["name"]
        if not acc.get("exists"):
            checks.append(("account", False, f"iPad account {n} is not made yet"))
        elif not acc.get("ours"):
            checks.append(("account", False, f"{n} is an account PPD did not make"))
        elif not acc.get("enabled"):
            checks.append(("account", False, f"iPad account {n} is switched off"))
        elif acc.get("access") is False:
            checks.append(("account", False, f"iPad account {n} may not use the folder"))
        else:
            checks.append(("account", True, f"iPad account {n} is ready"))
    return checks, (net["ip"] if net else "")


NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,19}$")
WORDS = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_password(n=12):
    """Easy to read back: no 0/O, 1/l/I."""
    return "".join(secrets.choice(WORDS) for _ in range(n))


def password_file(password):
    """The password for the admin window, in a file only this user can read; the window
    deletes it at once (Blender too, a little later, should the window never run)."""
    fd, path = tempfile.mkstemp(prefix="ppd_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(password)
    return path


def _token_user(advapi, token):
    """DOMAIN\\name of the account a logon token belongs to."""
    from ctypes import wintypes
    size = wintypes.DWORD()
    advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))      # 1: TokenUser
    buf = ctypes.create_string_buffer(size.value)
    if not advapi.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
        return ""
    sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
    name, dom = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
    n, d, use = wintypes.DWORD(256), wintypes.DWORD(256), ctypes.c_int()
    if not advapi.LookupAccountSidW(None, sid, name, ctypes.byref(n), dom, ctypes.byref(d),
                                    ctypes.byref(use)):
        return ""
    return dom.value + "\\" + name.value


def test_login(name, password):
    """0 when name and password are right on this PC, else the Windows error number
    (1326 wrong, 1331 switched off, 1909 locked). A wrong try counts toward a lock.
    Network logon with the password in clear (8): the plain network logon (3) lets any
    unknown name in as Guest when Guest is on, and the token is checked to be that account."""
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.LogonUserW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.LookupAccountSidW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR,
                                         ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
                                         ctypes.POINTER(wintypes.DWORD),
                                         ctypes.POINTER(ctypes.c_int)]
    token = wintypes.HANDLE()
    ok = advapi.LogonUserW(name, os.environ.get("COMPUTERNAME", "."), password, 8, 0,
                           ctypes.byref(token))
    if not ok:
        return ctypes.get_last_error()
    try:
        who = _token_user(advapi, token)
    finally:
        ctypes.windll.kernel32.CloseHandle(token)
    return 0 if who.split("\\")[-1].casefold() == name.casefold() else 1326


LOGIN_ERRORS = {1326: "wrong name or password", 1331: "the account is switched off",
                1909: "locked after wrong tries: wait 10 minutes",
                1385: "the account may not log in over the network"}


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
        self.account = ACCOUNT      # the iPad account to look for

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
                    d = detect(self.account)
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
