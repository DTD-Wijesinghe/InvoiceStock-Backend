# Run once from GitHub Desktop: Repository > Open in PowerShell, then ./Prepare-Git.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
# Remove only already-tracked files now covered by .gitignore. Local copies stay intact.
$ignoredTracked = @(git ls-files -ci --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect Git index.' }
foreach ($relativeFile in $ignoredTracked) {
    git rm --cached -- $relativeFile
    if ($LASTEXITCODE -ne 0) { throw "Could not untrack $relativeFile" }
}
Write-Host 'Ignored files are untracked; local files were preserved. Review changes in GitHub Desktop.'
