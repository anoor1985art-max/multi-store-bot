Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\AWS\Desktop\ملفات متنوعة\بوتات التليجرام\multi_store_bot"
WshShell.Run "python -u multi_store_bot.py", 0, False
