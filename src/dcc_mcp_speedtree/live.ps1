# Background control of a running SpeedTree Modeler through Windows UI Automation.
# Never moves the user's mouse or types into the focused window. Dialog answers are
# posted as window messages straight to the Modeler dialog. Prints one JSON object.
#   status                         instances, active document, open dialog, recent files
#   menu -Menu File -Item Save     invoke a menu entry; an unexpected dialog is cancelled
#   revert                         File > Revert to saved, confirming the warning
#   recent -Path <spm>             open a file through File > Recents (no file dialog)
#   screenshot -Path <png>         capture the window with PrintWindow (works while covered)
param(
    [Parameter(Mandatory = $true)][ValidateSet("status", "menu", "revert", "recent", "screenshot", "_invoke", "_document")][string]$Command,
    [int]$ProcessId = 0,
    [string]$Menu = "",
    [string]$Item = "",
    [string]$Path = "",
    [double]$Scale = 1.0,
    [int]$TimeoutMs = 120000
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public static class StLiveNative {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  static System.Collections.Generic.List<IntPtr> Windows(uint pid, bool popups) {
    var list = new System.Collections.Generic.List<IntPtr>();
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (p != pid || !IsWindowVisible(h)) return true;
      var c = new StringBuilder(256); GetClassName(h, c, 256);
      if (c.ToString().Contains("Popup") == popups) list.Add(h);
      return true;
    }, IntPtr.Zero);
    return list;
  }
  // Qt reports an open popup menu as the process main window; pick the titled frame instead.
  public static IntPtr MainFrame(uint pid) {
    foreach (var h in Windows(pid, false)) {
      var t = new StringBuilder(256); GetWindowText(h, t, 256);
      if (t.ToString().StartsWith("SpeedTree")) return h;
    }
    return IntPtr.Zero;
  }
  public static IntPtr[] Popups(uint pid) { return Windows(pid, true).ToArray(); }
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr c);
  public struct RECT { public int L, T, R, B; }
}
"@
# Per-monitor DPI awareness so window rectangles are physical pixels.
[void][StLiveNative]::SetThreadDpiAwarenessContext([IntPtr](-4))

$AE = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
$ExpandP = [System.Windows.Automation.ExpandCollapsePattern]::Pattern
$All = [System.Windows.Automation.Condition]::TrueCondition
# Qt only runs the action after UIA Invoke returns from its own modal loop, so the
# invoking client blocks while a dialog is open and stalls every other UIA call.
# The invoke therefore runs in a child process that is killed after this grace time.
# A process that already talked to UIA before the dialog opened stalls on every later
# UIA call, so callers create their first element only after Invoke-Detached returns.
$InvokeGraceMs = 2500

function Out-Json($obj) { $obj | ConvertTo-Json -Depth 6 -Compress; exit 0 }
function Fail($code, $msg, $extra = @{}) { $o = @{ ok = $false; error = $code; message = $msg }; foreach ($k in $extra.Keys) { $o[$k] = $extra[$k] }; $o | ConvertTo-Json -Depth 6 -Compress; exit 1 }
function Cond($prop, $val) { New-Object System.Windows.Automation.PropertyCondition($prop, $val) }
function And($a, $b) { New-Object System.Windows.Automation.AndCondition($a, $b) }

function Get-Instances {
    @(Get-Process SpeedTree_Modeler -ErrorAction SilentlyContinue | Where-Object { (Get-MainHwnd $_) -ne [IntPtr]::Zero })
}
function Get-MainHwnd($proc) { [StLiveNative]::MainFrame([uint32]$proc.Id) }
function Close-Popups($proc) {
    # Posted Escape closes Qt popup menus one level at a time.
    for ($i = 0; $i -lt 4; $i++) {
        $pops = [StLiveNative]::Popups([uint32]$proc.Id)
        if ($pops.Count -eq 0) { return }
        foreach ($h in $pops) {
            [void][StLiveNative]::PostMessage($h, 0x100, [IntPtr]0x1B, [IntPtr]0x00010001)
            [void][StLiveNative]::PostMessage($h, 0x101, [IntPtr]0x1B, [IntPtr]([int64]0xC0010001))
        }
        Start-Sleep -Milliseconds 200
    }
}
function Get-Modeler {
    $list = Get-Instances
    if ($ProcessId) { $list = @($list | Where-Object { $_.Id -eq $ProcessId }) }
    if ($list.Count -eq 0) { Fail "not_running" "No SpeedTree Modeler window found" }
    if ($list.Count -gt 1) { Fail "ambiguous_instance" "Several Modeler windows are open; pass process_id" @{ process_ids = @($list | ForEach-Object Id) } }
    return $list[0]
}
function Get-ActiveDocument($root) {
    # Only the active document exposes a Window element named after its file.
    foreach ($e in $root.FindAll($Scope::Descendants, (Cond $AE::ControlTypeProperty $CT::Window))) {
        if ($e.Current.Name -match '^(.+\.(spm|stt))\*?$') { return $Matches[1] }
    }
    return $null
}
function Get-ModalPane($root) {
    # Qt dialogs appear as named Pane children of the main window. While a dialog is
    # open every UIA round trip costs seconds, so filter on the provider side.
    $named = New-Object System.Windows.Automation.NotCondition((Cond $AE::NameProperty ""))
    return $root.FindFirst($Scope::Children, (And (Cond $AE::ControlTypeProperty $CT::Pane) $named))
}
function Wait-ModalPane($root, $ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) {
        try { $m = Get-ModalPane $root; if ($m) { return $m } } catch {}
        Start-Sleep -Milliseconds 200
    }
    return $null
}
function Send-DialogKey($pane, $vk, $scan) {
    # WM_KEYDOWN/WM_KEYUP posted to the dialog window; Qt accepts these, unlike posted clicks.
    $h = [IntPtr]$pane.Current.NativeWindowHandle
    [void][StLiveNative]::PostMessage($h, 0x100, [IntPtr]$vk, [IntPtr](1 -bor ($scan -shl 16)))
    [void][StLiveNative]::PostMessage($h, 0x101, [IntPtr]$vk, [IntPtr]([int64]0xC0000001 -bor ($scan -shl 16)))
}
function Close-Modal($root, $pane, $key) {
    # $key: "enter" accepts the default button, "escape" cancels.
    if ($key -eq "enter") { Send-DialogKey $pane 0x0D 0x1C } else { Send-DialogKey $pane 0x1B 0x01 }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt 10000) {
        Start-Sleep -Milliseconds 250
        try { if (-not (Get-ModalPane $root)) { return $true } } catch {}
    }
    return $false
}
function Open-TopMenu($root, $name) {
    $top = $root.FindFirst($Scope::Descendants, (And (Cond $AE::NameProperty $name) (Cond $AE::ControlTypeProperty $CT::MenuItem)))
    if (-not $top) { Fail "menu_not_found" "Menu '$name' not found (is a dialog open in Modeler?)" }
    $top.GetCurrentPattern($ExpandP).Expand()
    Start-Sleep -Milliseconds 350
    return $top
}
function Close-TopMenu($top) { try { $top.GetCurrentPattern($ExpandP).Collapse() } catch {} }
function Find-Child($parent, $match) {
    foreach ($e in $parent.FindAll($Scope::Descendants, $All)) { if (& $match $e.Current.Name) { return $e } }
    return $null
}
function Get-Recents($root) {
    $top = Open-TopMenu $root "File"
    $items = @()
    for ($try = 0; $try -lt 4 -and $items.Count -eq 0; $try++) {
        $rec = Find-Child $top { param($n) $n -eq "Recents" }
        if (-not $rec) { Start-Sleep -Milliseconds 300; continue }
        try { $rec.GetCurrentPattern($ExpandP).Expand() } catch {}
        Start-Sleep -Milliseconds (300 + 200 * $try)
        foreach ($e in $rec.FindAll($Scope::Descendants, $All)) {
            if ($e.Current.Name -match '^\d+\s+(.+)$') { $items += @{ label = $Matches[1]; element = $e } }
        }
    }
    return @{ top = $top; items = $items }
}
function Match-Elided($label, $full) {
    # Recents labels elide the middle of the path with "...".
    $f = $full.Replace('\', '/')
    $l = $label.Replace('\', '/')
    $parts = $l -split '\.\.\.'
    if ($parts.Count -eq 1) { return $f -ieq $l }
    # A dot next to the ellipsis may belong to the path ("v10.2....es"), so trim it.
    $head = $parts[0].TrimEnd('.'); $tail = $parts[-1].TrimStart('.')
    return $f.StartsWith($head, [StringComparison]::OrdinalIgnoreCase) -and $f.EndsWith($tail, [StringComparison]::OrdinalIgnoreCase)
}
function Quote-Arg($a) { if ("$a" -match '[\s"]') { '"' + ("$a" -replace '"', '\"') + '"' } else { "$a" } }
function Invoke-Child($p, $command, $childArgs, $waitMs) {
    # Runs this script in a fresh process; kills it after $waitMs.
    # Returns @{ finished; result } where result is the child's JSON when it finished.
    $out = [IO.Path]::GetTempFileName()
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath, "-Command", $command, "-ProcessId", $p.Id) + $childArgs
    $c = Start-Process powershell -ArgumentList (($argv | ForEach-Object { Quote-Arg $_ }) -join " ") -WindowStyle Hidden -PassThru -RedirectStandardOutput $out
    $finished = $c.WaitForExit($waitMs)
    if (-not $finished) { try { Stop-Process -Id $c.Id -Force } catch {} }
    $res = $null
    if ($finished) { $txt = Get-Content -Raw $out -ErrorAction SilentlyContinue; if ($txt) { try { $res = $txt.Trim() | ConvertFrom-Json } catch {} } }
    Remove-Item $out -ErrorAction SilentlyContinue
    return @{ finished = $finished; result = $res }
}
function Invoke-Detached($p, $childArgs) {
    $r = Invoke-Child $p "_invoke" $childArgs $InvokeGraceMs
    if ($r.result -and -not $r.result.ok) { Close-Popups $p; Fail $r.result.error $r.result.message }
    Close-Popups $p
    return $r
}
function Wait-DocumentFresh($p, $name) {
    # After a dialog this process' UIA connection stays stalled; ask a fresh process.
    $a = @("-TimeoutMs", $TimeoutMs); if ($name) { $a += @("-Path", $name) }
    $r = Invoke-Child $p "_document" $a ($TimeoutMs + 15000)
    if ($r.result -and $r.result.ok) { return $r.result.active_document }
    return $null
}
function Assert-NoModal($root) {
    $m = Get-ModalPane $root
    if ($m) { Fail "modal_dialog_open" "Modeler shows dialog '$($m.Current.Name)'; close it first" @{ dialog = $m.Current.Name } }
}

switch ($Command) {
    "_invoke" {
        # Child side of Invoke-Detached: find the entry and invoke it (may block on a dialog).
        $p = Get-Modeler; $root = $AE::FromHandle((Get-MainHwnd $p))
        Assert-NoModal $root
        if ($Path) {
            $full = [IO.Path]::GetFullPath($Path)
            $r = Get-Recents $root
            $hit = $r.items | Where-Object { Match-Elided $_.label $full } | Select-Object -First 1
            if (-not $hit) { Close-TopMenu $r.top; Fail "not_in_recents" "File is not in File > Recents; open it once with File > Open" @{ recent_files = @($r.items | ForEach-Object { $_.label }) } }
            $it = $hit.element
        } else {
            $top = Open-TopMenu $root $Menu
            $it = Find-Child $top { param($n) $n -eq $Item }
            if (-not $it) { Close-TopMenu $top; Fail "menu_item_not_found" "Menu item '$Menu > $Item' not found" }
            if (-not $it.Current.IsEnabled) { Close-TopMenu $top; Fail "menu_item_disabled" "Menu item '$Menu > $Item' is disabled" }
        }
        try { $it.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() } catch {}
        # Some entries (Save) leave the popup open after Invoke.
        Close-Popups $p
        Out-Json @{ ok = $true }
    }
    "_document" {
        # Wait until a document (optionally the file name in -Path) is active.
        $p = Get-Modeler; $root = $AE::FromHandle((Get-MainHwnd $p))
        $sw = [Diagnostics.Stopwatch]::StartNew(); $doc = $null
        while ($sw.ElapsedMilliseconds -lt $TimeoutMs) {
            try { if (-not (Get-ModalPane $root)) { $doc = Get-ActiveDocument $root } } catch {}
            if ($doc -and (-not $Path -or $doc -ieq $Path)) { Out-Json @{ ok = $true; active_document = $doc } }
            Start-Sleep -Milliseconds 300
        }
        Fail "timeout" "No matching document became active" @{ active_document = $doc }
    }
    "status" {
        $inst = @()
        foreach ($p in Get-Instances) {
            if ($ProcessId -and $p.Id -ne $ProcessId) { continue }
            $root = $AE::FromHandle((Get-MainHwnd $p))
            $modal = Get-ModalPane $root
            $recent = @()
            if (-not $modal) {
                $r = Get-Recents $root
                $recent = @($r.items | ForEach-Object { $_.label })
                Close-TopMenu $r.top
                Close-Popups $p
            }
            $inst += @{ process_id = $p.Id; started = $p.StartTime.ToString("s"); active_document = (Get-ActiveDocument $root)
                modal_dialog = $(if ($modal) { $modal.Current.Name } else { $null }); minimized = [StLiveNative]::IsIconic((Get-MainHwnd $p)); recent_files = $recent }
        }
        Out-Json @{ ok = $true; instances = $inst }
    }
    "menu" {
        $p = Get-Modeler
        $r = Invoke-Detached $p @("-Menu", $Menu, "-Item", $Item)
        $root = $AE::FromHandle((Get-MainHwnd $p))
        if (-not $r.finished) {
            $m = Wait-ModalPane $root 6000
            if ($m) {
                $name = $m.Current.Name
                $closed = Close-Modal $root $m "escape"
                Fail "dialog_cancelled" "'$Menu > $Item' opened dialog '$name'; it was cancelled" @{ dialog = $name; dialog_closed = $closed }
            }
        }
        Out-Json @{ ok = $true; process_id = $p.Id; invoked = "$Menu > $Item"; active_document = (Wait-DocumentFresh $p "") }
    }
    "revert" {
        $p = Get-Modeler
        $r = Invoke-Detached $p @("-Menu", "File", "-Item", "Revert to saved")
        $root = $AE::FromHandle((Get-MainHwnd $p))
        $m = Wait-ModalPane $root 60000
        if (-not $m) { Fail "no_confirmation" "Revert did not show its warning; document may be unchanged" }
        $name = $m.Current.Name
        if ($name -ne "Warning") {
            $closed = Close-Modal $root $m "escape"
            Fail "unexpected_dialog" "Revert opened dialog '$name'; it was cancelled" @{ dialog = $name; dialog_closed = $closed }
        }
        if (-not (Close-Modal $root $m "enter")) { Fail "dialog_stuck" "Revert warning did not close" }
        $after = Wait-DocumentFresh $p ""
        if (-not $after) { Fail "timeout" "Modeler did not reload the document in time" }
        Out-Json @{ ok = $true; process_id = $p.Id; active_document = $after }
    }
    "recent" {
        $p = Get-Modeler
        $full = [IO.Path]::GetFullPath($Path)
        # Opening a recent entry again adds a duplicate tab, so stop if it is already active.
        $already = Invoke-Child $p "_document" @("-TimeoutMs", 3000, "-Path", [IO.Path]::GetFileName($full)) 20000
        if ($already.result -and $already.result.ok) { Out-Json @{ ok = $true; process_id = $p.Id; opened = $full; active_document = $already.result.active_document; already_active = $true } }
        $r = Invoke-Detached $p @("-Path", $full)
        $root = $AE::FromHandle((Get-MainHwnd $p))
        if (-not $r.finished) {
            $m = Wait-ModalPane $root 6000
            if ($m) {
                $name = $m.Current.Name
                $closed = Close-Modal $root $m "escape"
                Fail "dialog_cancelled" "Opening showed dialog '$name' (unsaved changes?); it was cancelled" @{ dialog = $name; dialog_closed = $closed }
            }
        }
        $want = [IO.Path]::GetFileName($full)
        $doc = Wait-DocumentFresh $p $want
        if ($doc -ine $want) { Fail "timeout" "Modeler did not show '$want' in time" @{ active_document = $doc } }
        Out-Json @{ ok = $true; process_id = $p.Id; opened = $full; active_document = $doc }
    }
    "screenshot" {
        $p = Get-Modeler
        if (-not $Path) { Fail "path_required" "Screenshot output path required" }
        if ([StLiveNative]::IsIconic((Get-MainHwnd $p))) { Fail "minimized" "Modeler window is minimized; restore it to capture" }
        $rc = New-Object StLiveNative+RECT
        [void][StLiveNative]::GetWindowRect((Get-MainHwnd $p), [ref]$rc)
        $bmp = New-Object System.Drawing.Bitmap ($rc.R - $rc.L), ($rc.B - $rc.T)
        $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
        $ok = [StLiveNative]::PrintWindow((Get-MainHwnd $p), $dc, 2)   # PW_RENDERFULLCONTENT includes the GL viewport
        $g.ReleaseHdc($dc); $g.Dispose()
        if (-not $ok) { Fail "capture_failed" "PrintWindow failed" }
        if ($Scale -lt 1.0) {
            $small = New-Object System.Drawing.Bitmap ([int]($bmp.Width * $Scale)), ([int]($bmp.Height * $Scale))
            $g2 = [System.Drawing.Graphics]::FromImage($small)
            $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $g2.DrawImage($bmp, 0, 0, $small.Width, $small.Height); $g2.Dispose(); $bmp.Dispose(); $bmp = $small
        }
        $dir = Split-Path -Parent $Path
        if ($dir) { New-Item -ItemType Directory -Force $dir | Out-Null }
        $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
        Out-Json @{ ok = $true; process_id = $p.Id; path = $Path; width = $bmp.Width; height = $bmp.Height }
    }
}
