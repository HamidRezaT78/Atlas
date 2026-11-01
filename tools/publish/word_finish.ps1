param([string]$Docx, [string]$Out)
# Finish a generated .docx in Word: update the TOC and every field (PAGE/NUMPAGES in header/footer),
# then SaveAs2 as a native Word document. Refuses to write over an existing file. Exit code 0 = saved.
if (Test-Path -LiteralPath $Out) { Write-Error "exists, not overwritten: $Out"; exit 1 }
$word = New-Object -ComObject Word.Application
$word.Visible = $false; $word.DisplayAlerts = 0
$code = 1
try {
  $doc = $word.Documents.Open($Docx, $false, $false, $false)
  foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
  foreach ($story in $doc.StoryRanges) {
    $r = $story
    while ($r -ne $null) { [void]$r.Fields.Update(); $r = $r.NextStoryRange }
  }
  foreach ($toc in $doc.TablesOfContents) { $toc.Update() }  # again, now that page numbers are final
  $doc.SaveAs2($Out, 16)  # wdFormatDocumentDefault (.docx)
  "finished: $(Split-Path $Out -Leaf) pages=$($doc.ComputeStatistics(2)) TOCs=$($doc.TablesOfContents.Count)"
  $doc.Close($false)
  $code = 0
} catch { Write-Error $_ } finally { $word.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word) }
exit $code
