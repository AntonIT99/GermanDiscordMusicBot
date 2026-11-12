# Deployt den aktuellen lokalen Stand (inkl. uncommitteter Änderungen) direkt auf den Raspberry Pi.
#
#   .\deploy.ps1            Dateien kopieren, ggf. Requirements installieren, Bot neu starten
#   .\deploy.ps1 -Reqs      Requirements immer neu installieren (z.B. um yt-dlp zu aktualisieren)
#
# Kopiert werden alle Dateien, die Git kennt oder kennen würde (git ls-files + nicht ignorierte
# neue Dateien). Ignoriertes wie config.ini, bot.log, venv, music/* bleibt auf dem Pi unangetastet.
#
# Ziel kommt aus der Sektion [Deploy] in config.ini (host, bot_dir, service), siehe config.ini.example.
# Parameter -PiHost / -BotDir / -Service überschreiben die Werte.
param(
    [string]$PiHost,
    [string]$BotDir,
    [string]$Service,
    [switch]$Reqs
)
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Set-Location $PSScriptRoot

# [Deploy]-Sektion aus config.ini lesen
$deploy = @{}
$section = ""
if (Test-Path config.ini) {
    foreach ($line in Get-Content config.ini -Encoding utf8) {
        if ($line -match '^\s*\[(.+)\]\s*$') { $section = $Matches[1]; continue }
        if ($section -eq "Deploy" -and $line -match '^\s*([^#;=]+?)\s*=\s*(.*?)\s*$') { $deploy[$Matches[1]] = $Matches[2] }
    }
}
if (-not $PiHost)  { $PiHost  = $deploy["host"] }
if (-not $BotDir)  { $BotDir  = $deploy["bot_dir"] }
if (-not $Service) { $Service = if ($deploy["service"]) { $deploy["service"] } else { "bot" } }
if (-not $PiHost -or -not $BotDir) {
    throw "host und bot_dir fehlen: Sektion [Deploy] in config.ini anlegen (siehe config.ini.example)."
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) "nazarick-deploy"
New-Item -ItemType Directory -Force $tmp | Out-Null
$archive = Join-Path $tmp "bot.tar"
$listFile = Join-Path $tmp "files.txt"
$remoteScript = Join-Path $tmp "deploy-remote.sh"

# Dateiliste: getrackte + neue, nicht ignorierte Dateien (gelöschte überspringen)
$files = git ls-files --cached --others --exclude-standard | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
[IO.File]::WriteAllText($listFile, ($files -join "`n") + "`n")
tar -cf $archive -T $listFile
Write-Host "==> $($files.Count) Dateien gepackt ($(git log -1 --format='%h %s'))"

$remote = @'
set -euo pipefail
cd "$BOT_DIR"
old_req="$(sha1sum requirements.txt 2>/dev/null || true)"
tar -xmf /tmp/nazarick-bot.tar
# Windows-Zeilenenden (CRLF) in Textdateien auf LF umstellen
tar -tf /tmp/nazarick-bot.tar | while IFS= read -r f; do
  if [ -f "$f" ] && grep -Iq . "$f"; then sed -i 's/\r$//' "$f"; fi
done
rm -f /tmp/nazarick-bot.tar
if [ "$FORCE_REQS" = 1 ] || [ "$old_req" != "$(sha1sum requirements.txt)" ]; then
  echo "==> Installiere Requirements"
  venv/bin/pip install -q --upgrade -r requirements.txt
fi
echo "==> Starte $SERVICE neu"
sudo systemctl restart "$SERVICE"
sleep 3
systemctl --no-pager --lines=10 status "$SERVICE" || true
systemctl is-active --quiet "$SERVICE" || { echo "FEHLER: $SERVICE läuft nicht!" >&2; exit 1; }
'@
# LF-Zeilenenden, sonst stolpert bash über \r
[IO.File]::WriteAllText($remoteScript, ($remote -replace "`r", ""))

Write-Host "==> Kopiere nach ${PiHost}:$BotDir"
scp -q $archive "${PiHost}:/tmp/nazarick-bot.tar"
scp -q $remoteScript "${PiHost}:/tmp/nazarick-deploy.sh"

$force = if ($Reqs) { 1 } else { 0 }
ssh $PiHost "BOT_DIR='$BotDir' SERVICE='$Service' FORCE_REQS=$force bash /tmp/nazarick-deploy.sh; rc=`$?; rm -f /tmp/nazarick-deploy.sh; exit `$rc"

Remove-Item -Recurse -Force $tmp
Write-Host "==> Fertig."
