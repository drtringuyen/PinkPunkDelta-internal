# Run as administrator. Creates the local account ppdipad (or gives it a new password) for the iPad.
# You type the password; it is not saved or logged.
$ErrorActionPreference = 'Stop'
$name = 'ppdipad'
$acct = "$env:COMPUTERNAME\$name"
$made = $false
try {
  $me = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this as administrator' }
  if (-not (Get-SmbShare -Name PPD_Procreate -ErrorAction SilentlyContinue)) { throw 'PPD_Procreate is not shared: click Set Up This PC in Blender first' }
  $old = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
  if ($old) { Write-Host "$name exists already: this gives it a new password. Close the window to cancel." -ForegroundColor Yellow }
  while ($true) {
    $p1 = Read-Host 'Password (10 or more characters)' -AsSecureString
    $p2 = Read-Host 'Again' -AsSecureString
    if ($p1.Length -lt 10) { Write-Host 'Too short. Try again.' -ForegroundColor Yellow; continue }
    $c1 = New-Object System.Net.NetworkCredential('', $p1)
    $c2 = New-Object System.Net.NetworkCredential('', $p2)
    if ($c1.Password -ceq $c2.Password) { break }
    Write-Host 'The two did not match. Try again.' -ForegroundColor Yellow
  }
  if ($old) { Set-LocalUser -Name $name -Password $p1 }
  else {
    # In no group: not meant to sign in at the PC. Disabled until everything else is done.
    New-LocalUser -Name $name -Password $p1 -FullName 'PPD iPad' -Description 'iPad access to PPD_Procreate' -PasswordNeverExpires -AccountNeverExpires -UserMayNotChangePassword -Disabled | Out-Null
    $made = $true
  }
  foreach ($s in Get-SmbShare | Where-Object { -not $_.Special -and $_.Name -notin 'PPD_Procreate', 'print$' -and $_.ShareType -eq 'FileSystemDirectory' }) {
    Block-SmbShareAccess -Name $s.Name -AccountName $acct -Force | Out-Null
  }
  Grant-SmbShareAccess -Name PPD_Procreate -AccountName $acct -AccessRight Change -Force | Out-Null
  Enable-LocalUser -Name $name
  Write-Host "Done. On the iPad: smb://$env:COMPUTERNAME.local/PPD_Procreate   Name: $name" -ForegroundColor Green
} catch {
  if ($made) { Disable-LocalUser -Name $name -ErrorAction SilentlyContinue }
  Write-Host $_ -ForegroundColor Red
}
Read-Host 'Press Enter to close'
