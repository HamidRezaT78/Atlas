param([string]$Docx)
# Read-only: open in Word and report effective paragraph reading order, alignment and table direction.
# RESULT: PASS when every table is RTL, a TOC exists and the only non-empty LTR paragraphs outside code
# blocks are picture paragraphs (the client edition's relationship diagram). Exit code 0 = PASS.
$script:exit = 1; $script:ltrOutsideRowMarks = 0
$word = New-Object -ComObject Word.Application
$word.Visible = $false; $word.DisplayAlerts = 0
try {
  $doc = $word.Documents.Open($Docx, $false, $true, $false)
  $rtl = 0; $ltr = 0; $other = 0; $alignCounts = @{}; $codeLtr = 0
  foreach ($p in $doc.Paragraphs) {
    $ro = $p.ReadingOrder
    $style = $p.Style.NameLocal
    if ($style -eq 'Code Block') { if ($ro -eq 1) { $codeLtr++ }; continue }
    if ($ro -eq 0) { $rtl++ } elseif ($ro -eq 1) { $ltr++; if (-not $p.Range.Information(12) -or $p.Range.Text.Trim([char]13, [char]7, ' ').Length -gt 0) { $script:ltrOutsideRowMarks++ } } else { $other++ }
    $a = [string]$p.Alignment; $alignCounts[$a] = 1 + [int]$alignCounts[$a]
  }
  $tRtl = 0; $tLtr = 0
  foreach ($t in $doc.Tables) { if ($t.TableDirection -eq 0) { $tRtl++ } else { $tLtr++ } }
  "file: $(Split-Path $Docx -Leaf)"
  "  opened read-only OK; pages=$($doc.ComputeStatistics(2)) tables=$($doc.Tables.Count) paragraphs=$($doc.Paragraphs.Count) TOCs=$($doc.TablesOfContents.Count)"
  "  paragraph reading order (excluding code block): RTL=$rtl LTR=$ltr (of which non-empty or outside tables: $([int]$script:ltrOutsideRowMarks)) mixed=$other ; code-block paragraphs LTR=$codeLtr"
  "  alignment codes (0=left,1=center,2=right,3=justify): " + (($alignCounts.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name):$($_.Value)" }) -join ' ')
  "  tables RTL=$tRtl LTR=$tLtr ; section page orientation=$($doc.Sections.Item(1).PageSetup.Orientation) (1=landscape)"
  $pics = $doc.InlineShapes.Count
  $ok = ($tLtr -eq 0) -and ($doc.TablesOfContents.Count -ge 1) -and ([int]$script:ltrOutsideRowMarks -le $pics) -and ($other -eq 0)
  "  pictures=$pics  RESULT: $(if ($ok) { 'PASS' } else { 'FAIL' })"
  $doc.Close($false)
  $script:exit = if ($ok) { 0 } else { 1 }
} finally { $word.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word) }
exit $script:exit
