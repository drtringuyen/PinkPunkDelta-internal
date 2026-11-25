# iPad account `ppdipad`

The iPad saves into `PPD_Procreate` with this Windows account. Each computer has its **own**
`ppdipad`: it must be created on every PC, and a password set on one PC is unknown to the others.

| | |
|---|---|
| Address | `smb://<PC name>.local/PPD_Procreate` (PC name: type `hostname` in PowerShell) |
| Login | Registered User |
| Name | `ppdipad` (all lower case, no computer name, no e-mail) |
| Password | chosen in step 2; keep it in a password manager, **never in this repository** |

## 1. Blender, once per PC
Install the add-on. **PPD > 03.LiveLink > iPad Setup > Set Up This PC**, Yes. Every line needs a checkmark.

## 2. Create the account
In PowerShell, in this folder (`docs\ipad-account`); Windows asks for permission:

```powershell
Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\create_ppdipad.ps1`""
```

Type the password twice (10 or more characters). Nothing or only `*` appears. Wait for **Done.**
Running it again gives the account a new password.

It may read and write in `PPD_Procreate`, and is blocked from the other folders shared **at that
moment**. After sharing a new folder, run it again.

## 3. Check name and password on the PC, before the iPad

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\check_ppdipad.ps1
```

| Says | Do |
|---|---|
| OK | go on with the iPad |
| 1326 wrong name or password | type it again; forgotten: step 2 sets a new one |
| 1909 locked | wait 10 minutes, do not retry |
| 1331 disabled | run step 2 again |

OK proves the name and password. It does not test the network or the folder: that is step 4.

## 4. iPad
1. Files: eject old entries of this PC and restart the iPad (it may reuse a wrong saved login).
2. Files > ... > **Connect to Server** > the address above > **Registered User**.
3. Open `PPD_Procreate`: empty, without an error, is right.
4. Procreate: Share > PSD > Save to Files > `PPD_Procreate`, with the .blend open and LiveLink running.

Not asked for a password: the iPad uses an old login. Use the PC's name, not its number.
"Content Unavailable": on our first PC the log showed a wrong saved password. Do step 3, then 4.1.

## Remove
In an administrator PowerShell: `Remove-LocalUser -Name ppdipad`
