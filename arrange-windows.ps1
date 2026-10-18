param(
    [string]$KuramaHeadless = "false",
    [string]$NekoHeadless   = "true"
)

Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$sw = [int]$screen.Width
$sh = [int]$screen.Height
$halfW = [int]($sw / 2)
$halfH = [int]($sh / 2)

$csharp = @'
using System;
using System.Runtime.InteropServices;

public class WinTileHelper {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
}
'@

Add-Type -TypeDefinition $csharp -ErrorAction SilentlyContinue

# Mencari jendela dan memposisikan secara rapi berdampingan (multi-tasking layout)
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    Start-Sleep -Milliseconds 350

    $kHwnd = [WinTileHelper]::FindWindow([string]::Empty, "Nipnime - KURAMANIME Worker")
    if ($kHwnd -eq [IntPtr]::Zero) {
        $p = Get-Process | Where-Object { $_.MainWindowTitle -like "*KURAMANIME*" } | Select-Object -First 1
        if ($p) { $kHwnd = $p.MainWindowHandle }
    }

    $nHwnd = [WinTileHelper]::FindWindow([string]::Empty, "Nipnime - NEKOPOI Worker")
    if ($nHwnd -eq [IntPtr]::Zero) {
        $p = Get-Process | Where-Object { $_.MainWindowTitle -like "*NEKOPOI*" } | Select-Object -First 1
        if ($p) { $nHwnd = $p.MainWindowHandle }
    }

    if ($kHwnd -ne [IntPtr]::Zero) {
        if ($KuramaHeadless -eq "false") {
            # Kurama Brave Tampil: Terminal Kurama di separuh kiri atas
            [WinTileHelper]::MoveWindow($kHwnd, 0, 0, $halfW, $halfH, $true) | Out-Null
        } else {
            # Kurama Brave Hide: Terminal Kurama tinggi penuh kiri
            [WinTileHelper]::MoveWindow($kHwnd, 0, 0, $halfW, $sh, $true) | Out-Null
        }
    }

    if ($nHwnd -ne [IntPtr]::Zero) {
        if ($NekoHeadless -eq "false") {
            # Neko Brave Tampil: Terminal Neko di separuh kanan atas
            [WinTileHelper]::MoveWindow($nHwnd, $halfW, 0, $halfW, $halfH, $true) | Out-Null
        } else {
            # Neko Brave Hide: Terminal Neko tinggi penuh kanan
            [WinTileHelper]::MoveWindow($nHwnd, $halfW, 0, $halfW, $sh, $true) | Out-Null
        }
    }

    if ($kHwnd -ne [IntPtr]::Zero -and $nHwnd -ne [IntPtr]::Zero) {
        break
    }
}
