# Defensive Playbook — USB Initial Access, C2 Beaconing & Incident Response

> **Scope.** This playbook is defensive. It contains detection logic, incident-response steps, and hardening guidance for a USB-drop attack. It does **not** contain malware, exploit code, or instructions for disabling security controls. The companion physical exercise (`README_USB.md`) uses an inert PDF only.
>
> **Audience.** SOC analysts, detection engineers, Windows administrators, incident responders, and awareness-program owners.
>
> **Assumptions.** Windows 10/11 endpoints, Microsoft Defender for Endpoint (MDE) or Microsoft Sentinel, Sysmon where available, and a documented USB policy. Validate every rule in your own environment before production.

---

## 1. Detection Engineering

### 1.1 Sigma — USB mass-storage device insertion

This rule watches the Windows Driver Frameworks operational log. Event IDs `2003`/`2004` are commonly used for device arrival/removal; confirm the exact IDs on your build.

```yaml
title: USB Mass Storage Device Insertion
id: 5d2f0e5a-8c2b-4f7e-9a41-6b1f0c9d3a11
status: experimental
description: Detects a USB mass-storage device being added to a Windows endpoint.
references:
  - https://learn.microsoft.com/windows-hardware/drivers/usbcon/
author: HUMINT Shield
date: 2026/10/28
logsource:
  product: windows
  service: driver-framework
detection:
  selection:
    Provider_Name: 'Microsoft-Windows-DriverFrameworks-UserMode'
    EventID:
      - 2003
      - 2004
  condition: selection
falsepositives:
  - Approved USB drives used by IT or finance
  - USB keyboards and mice (not mass storage; tune by device class)
level: medium
tags:
  - attack.initial_access
  - attack.t1091
```

**Tuning.** Correlate with the device class and the user's normal behaviour. A USB keyboard is not the same risk as a mass-storage device. If your environment logs `EventID 2006` for device arrival, include it.

---

### 1.2 Sigma — Process execution from removable media

```yaml
title: Process Execution from Removable Media
id: 8b7d2c41-3a6e-4d0f-b2c8-9e5a1f7c6d22
status: experimental
description: Detects executables or script hosts launched from a non-system drive.
author: HUMINT Shield
date: 2026/10/28
logsource:
  category: process_creation
  product: windows
detection:
  selection_image:
    Image|startswith:
      - 'D:\'
      - 'E:\'
      - 'F:\'
      - 'G:\'
      - 'H:\'
  selection_ext:
    Image|endswith:
      - '.exe'
      - '.scr'
      - '.com'
      - '.pif'
      - '.bat'
      - '.cmd'
      - '.js'
      - '.vbs'
      - '.lnk'
  condition: selection_image and selection_ext
falsepositives:
  - Legitimate portable applications approved by IT
  - Software installation from an approved USB drive
level: high
tags:
  - attack.initial_access
  - attack.t1091
  - attack.t1204.002
```

**Tuning.** Drive letters vary. If you use a endpoint management tool, map removable volumes by device path instead of `D:`–`H:`. Exclude approved software-distribution drives.

---

### 1.3 Sigma — Double-extension file created on removable media

```yaml
title: Double-Extension File Created on Removable Media
id: c3a91f60-7e4b-4a2d-8f1e-2d6b9c0a4e33
status: experimental
description: Detects files such as report.pdf.exe written to a removable drive.
author: HUMINT Shield
date: 2026/10/28
logsource:
  category: file_event
  product: windows
detection:
  selection:
    TargetFilename|re: '(?i)\\[^\\]+\.(pdf|docx?|xlsx?|pptx?|jpg|jpeg|png|txt)\.(exe|scr|bat|cmd|com|pif|js|vbs|lnk)$'
  condition: selection
falsepositives:
  - Rare legitimate dual-extension files created by developers
level: high
tags:
  - attack.initial_access
  - attack.t1036.007
  - attack.t1204.002
```

**Tuning.** Sigma regex behaviour differs by backend. In Splunk, use `rex` or a `regex` command; in Sentinel, use KQL `matches regex`. Test against your file-event source (Sysmon Event ID 11 or MDE `DeviceFileEvents`).

---

### 1.4 Sigma — Office application spawning a shell

```yaml
title: Office Application Spawning Shell or Script Host
id: 1f4e8b2a-6c3d-4b9e-a7f0-5d2c8e1b9a44
status: stable
description: Detects Word/Excel/PowerPoint creating cmd, PowerShell, WScript, MSHTA or Rundll32.
author: HUMINT Shield
date: 2026/10/28
logsource:
  category: process_creation
  product: windows
detection:
  selection_parent:
    ParentImage|endswith:
      - '\WINWORD.EXE'
      - '\EXCEL.EXE'
      - '\POWERPNT.EXE'
      - '\OUTLOOK.EXE'
  selection_child:
    Image|endswith:
      - '\cmd.exe'
      - '\powershell.exe'
      - '\pwsh.exe'
      - '\wscript.exe'
      - '\cscript.exe'
      - '\mshta.exe'
      - '\rundll32.exe'
      - '\regsvr32.exe'
  condition: selection_parent and selection_child
falsepositives:
  - Approved Office add-ins or macros with documented business use
level: high
tags:
  - attack.execution
  - attack.t1204.002
  - attack.t1059
```

---

### 1.5 KQL — USB mounts in Microsoft Defender for Endpoint

```kusto
// USB mass-storage mounts in the last 30 days.
// If your tenant does not expose UsbDriveMounted, use:
//   DeviceEvents | where ActionType has "Usb"
DeviceEvents
| where Timestamp > ago(30d)
| where ActionType =~ "UsbDriveMounted"
| project Timestamp, DeviceName, AccountName, ActionType, AdditionalFields
| order by Timestamp desc
```

**Use it for:** baseline approved USB usage, identify unusual users/devices, and trigger an investigation when a high-risk user mounts an unknown device.

---

### 1.6 KQL — Process execution from a removable drive

```kusto
// Processes launched from D: through Z:. Tune the drive letters and exclusions.
DeviceProcessEvents
| where Timestamp > ago(30d)
| where FolderPath matches regex @"^[D-Z]:\\"
| where FileName in~ (
    "cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe",
    "cscript.exe", "mshta.exe", "rundll32.exe", "regsvr32.exe"
) or FolderPath matches regex @"(?i)\.(exe|scr|com|pif|bat|cmd|js|vbs|lnk)$"
| project Timestamp, DeviceName, AccountName, FileName, FolderPath,
          ProcessCommandLine, InitiatingProcessFileName, InitiatingProcessAccountName
| order by Timestamp desc
```

**Use it for:** the highest-fidelity USB initial-access signal. A user double-clicking a document that launches `cmd.exe` from `E:\` is almost always malicious.

---

### 1.7 KQL — Double-extension files

```kusto
DeviceFileEvents
| where Timestamp > ago(30d)
| where FileName matches regex @"(?i)\.(pdf|docx?|xlsx?|pptx?|jpg|jpeg|png|txt)\.(exe|scr|bat|cmd|com|pif|js|vbs|lnk)$"
| project Timestamp, DeviceName, AccountName, FolderPath, FileName,
          ActionType, SHA256, InitiatingProcessFileName
| order by Timestamp desc
```

**Use it for:** catching the lure before execution. Alert on creation, not only execution, so the SOC can remove the file and warn the user.

---

### 1.8 KQL — C2 beaconing heuristic

Perfectly regular beacons are rare in real malware because operators add jitter. Start with repeated connections to the same public destination and a stable process, then enrich with threat intelligence.

```kusto
let lookback = 7d;
DeviceNetworkEvents
| where Timestamp > lookback
| where RemoteIPType == "Public"
| where ActionType == "ConnectionSuccess"
| summarize
    Connections = count(),
    FirstSeen = min(Timestamp),
    LastSeen = max(Timestamp),
    Ports = make_set(RemotePort, 10),
    Processes = make_set(InitiatingProcessFileName, 10)
    by DeviceName, RemoteIP
| where Connections between (6 .. 500)
| extend SpanMinutes = datetime_diff('minute', LastSeen, FirstSeen)
| where SpanMinutes >= 30
| extend AvgMinutesBetween = iff(Connections > 1, todouble(SpanMinutes) / (Connections - 1), 0.0)
| where AvgMinutesBetween between (1.0 .. 120.0)
| order by Connections desc
```

**Interpretation.** A browser or Teams will also produce repeated connections. Prioritise rare destinations (seen on one or two devices), non-standard ports, and processes that are not browsers, updaters, or collaboration tools. Add a `RemoteIP !in (known_good_ips)` filter using your own inventory.

---

### 1.9 KQL — Rare external destinations

```kusto
DeviceNetworkEvents
| where Timestamp > ago(30d)
| where RemoteIPType == "Public"
| summarize
    DeviceCount = dcount(DeviceName),
    Connections = count(),
    FirstSeen = min(Timestamp),
    LastSeen = max(Timestamp),
    SampleProcess = any(InitiatingProcessFileName)
    by RemoteIP
| where DeviceCount <= 2 and Connections >= 5
| order by Connections desc
```

**Use it for:** finding infrastructure that is not part of your normal SaaS estate. Enrich the IP with VirusTotal, GreyNoise, or your TI platform before blocking.

---

### 1.10 KQL — Suspicious PowerShell from a user context

```kusto
DeviceProcessEvents
| where Timestamp > ago(30d)
| where FileName in~ ("powershell.exe", "pwsh.exe")
| where ProcessCommandLine has_any (
    "-enc", "-encodedcommand", "FromBase64String", "IEX",
    "DownloadString", "Invoke-WebRequest", "hidden", "bypass"
)
| project Timestamp, DeviceName, AccountName, ProcessCommandLine,
          InitiatingProcessFileName, InitiatingProcessAccountName
| order by Timestamp desc
```

**Use it for:** post-USB execution. Correlate with the USB mount and file-creation events in the same 15-minute window.

---

### 1.11 Correlation idea — USB → file → process → network

A single alert is noisy. A high-confidence incident looks like this sequence on one device within minutes:

```text
UsbDriveMounted
  → FileCreated: E:\راتب_الشهر_القادم.pdf.exe
  → ProcessCreated: E:\راتب_الشهر_القادم.pdf.exe
  → NetworkConnection: public IP:443
  → ProcessCreated: powershell.exe -enc ...
```

Build a Sentinel analytics rule or an MDE custom detection that joins these tables by `DeviceName` and `Timestamp`. Require at least three stages before paging.

---

## 2. Incident Response Playbook — USB Drop

### 2.1 Roles

| Role | Responsibility |
|---|---|
| SOC analyst (L1) | Triage, preserve initial evidence, open the incident |
| Incident responder (L2/L3) | Containment, eradication, recovery, root cause |
| Endpoint administrator | GPO/Intune changes, device isolation, reimaging |
| Communications lead | Internal messaging, legal/HR coordination |
| Awareness owner | Debrief the employee, update training, measure impact |

### 2.2 Phase 0 — Preparation

- [ ] Written USB policy: who may use removable media, approval process, approved encrypted drives.
- [ ] EDR with device-control and file-event visibility.
- [ ] Sysmon or equivalent logging on high-risk endpoints.
- [ ] Centralised log retention (at least 90 days).
- [ ] Break-glass procedure for USB exceptions.
- [ ] Contact list for legal, HR, privacy, and communications.
- [ ] Tabletop exercise at least twice a year.

### 2.3 Phase 1 — Identification

1. **Do not execute the file.** If it is already running, isolate the host from the network (EDR isolation, not shutdown, to preserve memory).
2. Record the device, user, hostname, time, drive letter, file name, size, and SHA-256.
3. Take a photo of the USB drive and its label.
4. Collect read-only evidence:
   ```powershell
   Get-PnpDevice -Class USB | Format-Table -AutoSize
   Get-Volume | Format-Table -AutoSize
   Get-CimInstance Win32_USBControllerDevice | Select-Object -First 20
   Get-WinEvent -LogName 'Microsoft-Windows-DriverFrameworks-UserMode/Operational' -MaxEvents 100
   ```
5. Check EDR for process creation and network connections from the removable drive.
6. Ask the user what they saw and did — without blaming them.
7. Classify: attempted access (file opened but no execution), execution (process started), or compromise (C2/credential access/lateral movement).

### 2.4 Phase 2 — Containment

**Short term**

- Isolate the endpoint in EDR.
- Disable the user's active sessions and reset credentials if execution is confirmed.
- Block the file hash, C2 IP/domain, and any dropped binaries.
- Disable USB mass storage for the affected endpoint group via GPO/Intune.

**GPO paths**

```text
Computer Configuration
  → Administrative Templates
    → System
      → Device Installation
        → Device Installation Restrictions
          → Prevent installation of removable devices            [Enabled]
      → Removable Storage Access
        → All Removable Storage classes: Deny all access          [Enabled]
```

Also disable AutoPlay:

```text
Computer Configuration
  → Administrative Templates
    → Windows Components
      → AutoPlay Policies
        → Turn off Autoplay                                      [Enabled]
        → All drives
```

**Intune**

- `Devices → Configuration profiles → Create profile → Templates → Administrative Templates`
- `Endpoint security → Attack surface reduction → Device control` for granular USB allow/deny lists.

### 2.5 Phase 3 — Eradication

- Remove dropped files, scheduled tasks, services, Run keys, and WMI event subscriptions.
- Check for new local users, added SSH keys, and browser extensions.
- Run a full EDR scan and a Defender offline scan if persistence is suspected.
- If the endpoint is domain-joined and credentials may have been exposed, reset the user's password and rotate any cached secrets.
- Reimage when the root cause is uncertain. A clean rebuild is cheaper than a repeat incident.

### 2.6 Phase 4 — Recovery

- Reconnect the endpoint only after verification.
- Re-enable USB only for approved users and encrypted devices.
- Monitor the endpoint for 72 hours with heightened logging.
- Confirm business applications and data integrity.
- Inform the user about the outcome and the training they should complete.

### 2.7 Phase 5 — Post-incident

- [ ] Timeline of the incident.
- [ ] Root cause: policy gap, detection gap, or user behaviour.
- [ ] Detection improvements: new Sigma/KQL rule, tuned false positives.
- [ ] Hardening changes: ASR, device control, WDAC/AppLocker.
- [ ] Awareness update: add the exact lure to the training library.
- [ ] Metrics: time to detect, time to contain, time to recover.
- [ ] Legal/privacy review if personal data was exposed.
- [ ] Close the incident and share a blameless lessons-learned note.

### 2.8 Communication template

> **Subject: Security incident — USB device on [hostname]**
>
> We identified a USB device that may have attempted to run an unknown file on [hostname] at [time]. The endpoint has been isolated and we are investigating. No action is required from you at this time. If you plugged in a USB drive today, please contact the security team. We will share an update within [time].

Keep communication factual. Do not speculate about attribution or data loss.

---

## 3. Hardening Recommendations

### 3.1 Attack Surface Reduction (ASR) rules

Enable in audit mode first, then block. Common rules for USB and script-based initial access:

| Rule | GUID |
|---|---|
| Block untrusted and unsigned processes that run from USB | `B2B3F03D-6A65-4F7B-A9C7-1C7EF74A9BA4` |
| Block executable files from running unless they meet prevalence, age, or trusted list criteria | `01443614-CD74-433A-B99E-2ECDC07BFC25` |
| Block Office applications from creating child processes | `D4F940AB-401B-4EFC-AADC-AD5F3C50688A` |
| Block Office applications from injecting code into other processes | `75668C1F-73B5-4CF0-BB93-3ECF5CB7CC84` |
| Block Win32 API calls from Office macros | `92E97FA1-2EDF-4476-BDD6-9DD0B4DDDC7B` |
| Block execution of potentially obfuscated scripts | `5BEB7EFE-FD9A-4556-801D-275E5FFC04CC` |
| Block JavaScript or VBScript from launching downloaded executable content | `D3E037E1-3EB8-44C8-A917-57927947596D` |
| Block process creations originating from PSExec and WMI commands | `D1E49AAC-8F56-4280-B9BA-993A6D77406C` |
| Block credential stealing from LSASS | `9E6C4E1F-7D60-472F-BA1A-A39EF669E4B2` |
| Block abuse of exploited vulnerable signed drivers | `56A863A9-875E-4185-98A7-B882C64B5CE5` |
| Block rebooting machine in Safe Mode | `33DDEDF1-C6E0-47CB-833E-DE6133960387` |
| Block use of copied or impersonated system tools | `C0033C00-D16D-4114-A5A0-DC9B3A7D2CEB` |
| Block persistence through WMI event subscription | `E6DB77E5-3DF2-4CF1-B95A-636979351E5B` |
| Block Adobe Reader from creating child processes | `7674BA52-37EB-4A4F-A9A1-F0F9A1619A2C` |
| Block Office communication application from creating child processes | `26190899-1602-49E8-8B27-EB1D0A1CE869` |

PowerShell example (one rule at a time):

```powershell
Add-MpPreference `
  -AttackSurfaceReductionRules_Ids B2B3F03D-6A65-4F7B-A9C7-1C7EF74A9BA4 `
  -AttackSurfaceReductionRules_Actions Enabled
```

Verify:

```powershell
Get-MpPreference | Select-Object AttackSurfaceReductionRules_Ids, AttackSurfaceReductionRules_Actions
```

### 3.2 Device control and USB policy

- Allow only company-issued, encrypted USB drives.
- Block mass storage for standard users; allow keyboards and mice.
- Require approval for exceptions; expire exceptions automatically.
- Log every mount and every file copied to removable media.
- Use Microsoft Defender Device Control (Intune) or a third-party DLP equivalent.
- Encrypt approved drives with BitLocker To Go.
- Label approved drives and publish a "found a USB?" procedure.

### 3.3 Application control

- **WDAC** (Windows Defender Application Control): block executables from removable media; use a signed policy and audit mode first.
- **AppLocker**: deny `E:\*` and other removable paths for standard users; allow approved publishers.
- Block `cmd.exe`, `powershell.exe`, `wscript.exe`, `cscript.exe`, and `mshta.exe` for users who do not need them.
- Enforce PowerShell Constrained Language Mode and script-block logging.

### 3.4 Browser and email hardening

- Disable automatic download of executables.
- Enable SmartScreen for apps and files.
- Block macros from the internet (`Block macros from running in Office files from the Internet`).
- Disable OLE and ActiveX objects in Office.
- Enable Controlled Folder Access for ransomware protection.
- Use Protected View for files from removable media.

### 3.5 Identity and credential hygiene

- Enable LAPS for local administrator passwords.
- Require phishing-resistant MFA for privileged accounts.
- Block legacy authentication.
- Rotate credentials after a confirmed USB execution.
- Monitor for token theft and impossible-travel sign-ins.

### 3.6 Logging checklist

- [ ] Sysmon Event IDs 1, 3, 6, 11, 13, 22.
- [ ] Windows Security 4624, 4625, 4672, 4688, 4698, 7045.
- [ ] DriverFrameworks-UserMode/Operational 2003/2004.
- [ ] PowerShell 4103/4104.
- [ ] Defender operational and ASR events.
- [ ] EDR device-control events.

---

## 4. Safe USB-Drop Exercise Mapping

The `README_USB.md` exercise deliberately uses **only** an inert PDF. Map its telemetry to the detections above for a realistic tabletop:

| Exercise event | Defensive analogue | Detection |
|---|---|---|
| `usb_opened` | User opens a lure from removable media | File creation + process execution |
| Training redirect | Containment/awareness moment | No host execution |
| Elo −25 | Behavioural risk signal | HR/awareness metric |
| Report to security | Successful detection by the user | Report inbox event |

**Do not** add an executable, macro, script, or autorun file to make the exercise "more realistic." The PDF already tests the human decision that matters: whether the employee trusts an unknown USB drive.

---

## 5. Metrics That Matter

| Metric | Target |
|---|---|
| USB mounts per 1,000 endpoints per month | Baseline, then reduce |
| Time from USB mount to SOC alert | < 5 minutes for high-risk users |
| Percentage of endpoints with device control | 100% of high-risk groups |
| ASR rules in block mode | ≥ 90% of endpoints |
| USB-drop exercise plug-in rate | Measure; aim to reduce quarter over quarter |
| USB-drop report rate | Measure; aim to increase |
| Time to report after opening | < 15 minutes |
| Training completion after the exercise | ≥ 90% within 7 days |

---

## 6. References

- MITRE ATT&CK T1091 — Replication Through Removable Media.
- MITRE ATT&CK T1204.002 — User Execution: Malicious File.
- MITRE ATT&CK T1059 — Command and Scripting Interpreter.
- Microsoft Defender for Endpoint — Device control and ASR documentation.
- Microsoft Sentinel — KQL reference and analytics rules.
- SigmaHQ — Sigma rule specification.
- NIST SP 800-61 — Incident Handling Guide.
- CISA — USB device security guidance.
- `README_USB.md` — safe physical exercise guide.

---

## 7. Change Log

| Date | Change |
|---|---|
| 2026-10-28 | Initial version: Sigma/KQL detections, IR playbook, ASR/GPO hardening, exercise mapping |
