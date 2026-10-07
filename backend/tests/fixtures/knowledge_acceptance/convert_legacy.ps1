# Convert the legacy Office acceptance samples with Word / PowerPoint COM.
#
#   _legacy_doc.docx -> sample.doc  (Word 97-2003 binary, wdFormatDocument97 = 0)
#   _legacy_ppt.pptx -> sample.ppt  (PowerPoint 97-2003 binary, ppSaveAsPresentation = 1)
#
# Both outputs are verified by magic bytes: a real legacy file is an OLE
# compound file starting with D0 CF 11 E0; zip bytes (PK) mean the wrong
# format was produced and the script fails. Intermediates are removed only
# after both outputs pass. Requires desktop Office; run:
#
#   pwsh -NoProfile -File convert_legacy.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$docSrc = Join-Path $root "_legacy_doc.docx"
$pptSrc = Join-Path $root "_legacy_ppt.pptx"
$docDst = Join-Path $root "sample.doc"
$pptDst = Join-Path $root "sample.ppt"

foreach ($p in @($docSrc, $pptSrc)) {
    if (-not (Test-Path $p)) { throw "missing source $p -- run make_samples.py first" }
}

function Test-OleMagic([string]$Path) {
    $b = [System.IO.File]::ReadAllBytes($Path)[0..3]
    return ($b[0] -eq 0xD0) -and ($b[1] -eq 0xCF) -and ($b[2] -eq 0x11) -and ($b[3] -eq 0xE0)
}

# --- Word: .docx -> .doc -----------------------------------------------
$word = New-Object -ComObject Word.Application
try {
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open($docSrc)
    try {
        $doc.SaveAs2($docDst, 0)   # wdFormatDocument97
    } finally {
        $doc.Close(0)              # wdDoNotSaveChanges
    }
} finally {
    $word.Quit()
}
if (-not (Test-OleMagic $docDst)) { throw "sample.doc is not an OLE compound file" }
Write-Host ("sample.doc  {0} bytes  magic OK" -f (Get-Item $docDst).Length)

# --- PowerPoint: .pptx -> .ppt -----------------------------------------
$ppt = New-Object -ComObject PowerPoint.Application
try {
    $ppt.DisplayAlerts = 1         # ppAlertsNone
    $pres = $ppt.Presentations.Open($pptSrc, $true, $false, $false)
    try {
        $pres.SaveAs($pptDst, 1)   # ppSaveAsPresentation -> 97-2003 when saving as .ppt
    } finally {
        $pres.Close()
    }
} finally {
    $ppt.Quit()
}
if (-not (Test-OleMagic $pptDst)) { throw "sample.ppt is not an OLE compound file (wrong PowerPoint format id?)" }
Write-Host ("sample.ppt  {0} bytes  magic OK" -f (Get-Item $pptDst).Length)

Remove-Item $docSrc, $pptSrc
Write-Host "removed intermediates; sample.doc / sample.ppt ready"
