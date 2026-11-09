"""Fixed Windows offline dictation program. Request data enters through stdin.

The child only enumerates installed recognizers or decodes the supplied WAV in
memory. It never opens an audio device, writes files or executes request text.
"""

POWERSHELL = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$engine = $null
$stream = $null
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    Add-Type -AssemblyName System.Speech
    $installed = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
        Where-Object { $_.Culture.Name -in @('en-US','en-GB','en-IN','hi-IN') })
    if ($request.operation -eq 'status') {
        @{ok=$true; locales=@($installed | ForEach-Object { $_.Culture.Name } | Sort-Object -Unique)} | ConvertTo-Json -Compress
        exit 0
    }
    if ($request.operation -ne 'transcribe') { throw 'Unsupported operation' }
    $recognizer = $installed | Where-Object { $_.Culture.Name -ceq $request.locale } | Select-Object -First 1
    if (-not $recognizer) { throw 'Requested local language unavailable' }
    $bytes = [Convert]::FromBase64String($request.audio)
    if ($bytes.Length -gt 700000) { throw 'Input limit' }
    $stream = [IO.MemoryStream]::new($bytes, $false)
    $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new($recognizer)
    $engine.InitialSilenceTimeout = [timespan]::FromSeconds(2)
    $engine.BabbleTimeout = [timespan]::FromSeconds(2)
    $engine.EndSilenceTimeout = [timespan]::FromMilliseconds(500)
    $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
    $engine.SetInputToWaveStream($stream)
    $parts = [Collections.Generic.List[string]]::new()
    $weighted = 0.0
    $characters = 0
    for ($index = 0; $index -lt 32; $index++) {
        # EOF can coincide with a valid final result. System.Speech then clears
        # its input; another Recognize call throws and would lose all prior text.
        if ($null -eq $engine.AudioFormat) { break }
        $heard = $engine.Recognize([timespan]::FromSeconds(3))
        if (-not $heard) { break }
        $characters += $heard.Text.Length
        if ($characters -gt 8000) { throw 'Result limit' }
        $parts.Add($heard.Text)
        $weighted += [double]$heard.Confidence * $heard.Text.Length
    }
    $confidence = if ($characters) { $weighted / $characters } else { 0.0 }
    @{ok=$true; text=($parts -join ' '); confidence=$confidence; locale=$recognizer.Culture.Name} | ConvertTo-Json -Compress
} catch {
    @{ok=$false; error='recognizer_unavailable'} | ConvertTo-Json -Compress
    exit 1
} finally {
    if ($engine) { $engine.Dispose() }
    if ($stream) { $stream.Dispose() }
}
'''
