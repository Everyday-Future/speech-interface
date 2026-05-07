' launch_sd_transcriber_silent.vbs - Completely silent launcher for SD Card Transcriber
Set WshShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Get the directory where this script is located
strPath = objFSO.GetParentFolderName(WScript.ScriptFullName)

' Build the path to the batch file
strBatchFile = strPath & "\sd_transcriber.bat"

' Check if batch file exists
If objFSO.FileExists(strBatchFile) Then
    ' Run the batch file hidden (0 = hidden window)
    WshShell.Run Chr(34) & strBatchFile & Chr(34), 0, False
Else
    ' If batch file doesn't exist, try to run sd_transcriber.pyw directly
    strPythonScript = strPath & "\sd_transcriber.pyw"
    If objFSO.FileExists(strPythonScript) Then
        WshShell.Run "pythonw """ & strPythonScript & """", 0, False
    Else
        MsgBox "Could not find sd_transcriber.bat or sd_transcriber.pyw", 16, "Error"
    End If
End If
