param([Parameter(Mandatory=$true)][string]$DataDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$taskNarrator = New-Object System.Speech.Synthesis.SpeechSynthesizer
$taskProject = Get-Content -LiteralPath (Join-Path $DataDirectory 'projects/demo_suspense.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskVoices = @{'narrator'='Microsoft Huihui Desktop';'lin'='Microsoft Kangkang';'xu'='Microsoft Yaoyao'}
foreach ($taskEvent in $taskProject.events) {
    if ($taskEvent.kind -ne 'speech') { continue }
    $taskOutput = Join-Path $DataDirectory ('assets/' + $taskEvent.asset_id + '.wav')
    if (Test-Path -LiteralPath $taskOutput) { continue }
    try { $taskNarrator.SelectVoice($taskVoices[$taskEvent.character_id]) }
    catch { $taskNarrator.SelectVoice('Microsoft Huihui Desktop') }
    $taskNarrator.Rate = if ($taskEvent.character_id -eq 'lin') { -1 } else { 0 }
    $taskNarrator.SetOutputToWaveFile($taskOutput)
    $taskNarrator.Speak($taskEvent.text)
    $taskNarrator.SetOutputToNull()
}
$taskNarrator.Dispose()
