# Tells whether a name and password are right on THIS PC. No admin needed; changes nothing, saves nothing.
# A wrong password counts as a failed login: too many lock the account for a while.
param([string]$Name = 'ppdipad', [securestring]$Password)
Add-Type -Namespace PPD -Name Logon -MemberDefinition @'
[DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
public static extern bool LogonUser(string user, string domain, string password, int type, int provider, out IntPtr token);
[DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
'@
$ask = -not $Password
if ($ask) { $Password = Read-Host "Password of $Name" -AsSecureString }
$t = [IntPtr]::Zero
$ok = [PPD.Logon]::LogonUser($Name, $env:COMPUTERNAME, (New-Object System.Net.NetworkCredential('', $Password)).Password, 3, 0, [ref]$t)
$code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
if ($ok) { [void][PPD.Logon]::CloseHandle($t); Write-Host "OK: $Name and this password are correct on $env:COMPUTERNAME" -ForegroundColor Green }
else {
  $why = switch ($code) {
    1326 { 'wrong name or wrong password' }
    1331 { 'the account is disabled' }
    1909 { 'the account is locked: wait 10 minutes' }
    1385 { 'the account may not log in over the network' }
    default { (New-Object ComponentModel.Win32Exception $code).Message }
  }
  Write-Host "NOT OK ($code): $why" -ForegroundColor Red
}
if ($ask) { Read-Host 'Press Enter to close' }
