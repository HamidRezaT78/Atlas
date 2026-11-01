param([string]$Pdf, [string]$OutPrefix, [int[]]$Pages, [int]$Width = 1600)
# Render PDF pages to PNG with the built-in Windows.Data.Pdf API (offline). Run with Windows PowerShell 5.1.
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, [Type]$t) { $task = $asTaskGeneric.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
function AwaitAction($op) { $task = $asTaskAction.Invoke($null, @($op)); $task.Wait(-1) | Out-Null }

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $Pdf).Path)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
"pdf pages: $($doc.PageCount)"
Add-Type -AssemblyName System.Drawing
foreach ($n in $Pages) {
  if ($n -gt $doc.PageCount) { "skip page $n (beyond end)"; continue }
  $page = $doc.GetPage($n - 1)
  $opts = New-Object Windows.Data.Pdf.PdfPageRenderOptions
  $opts.DestinationWidth = $Width
  $opts.DestinationHeight = [uint32]($Width * $page.Size.Height / $page.Size.Width)
  $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
  AwaitAction ($page.RenderToStreamAsync($stream, $opts))
  $net = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream.GetInputStreamAt(0))
  $out = "{0}-r{1:D3}.png" -f $OutPrefix, $n
  $fs = [IO.File]::Create($out); $net.CopyTo($fs); $fs.Close(); $net.Dispose(); $stream.Dispose(); $page.Dispose()
  "saved $out"
}
