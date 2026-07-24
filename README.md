# WTTG3 Auto Gambler

Unofficial Windows UI automation for the Meramun slot machine in *Welcome to
the Game III*. It records your own setup/restart inputs, continuously spins,
checks the YoloYen target three times, pauses with Escape at the target, and
restarts a lost run when the balance is low and the reels are static.

## Requirements

- Windows 10 or 11
- Python 3.11 or newer
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
- *Welcome to the Game III*

The project contains no game files, recorded inputs, or user-specific paths.
Recordings are resolution-sensitive; keep the same game resolution and window
position when replaying them.

## Install

```powershell
git clone https://github.com/beratkaratass/wttg3-auto-gambler.git
cd wttg3-auto-gambler
py -3 -m pip install -r requirements.txt
```

If Tesseract is not in `PATH`, set it before launching:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## Use

Run `run.bat` or:

```powershell
py -3 wttg3_auto_gambler.py
```

In the controller:

1. Record the complete main-menu-to-gambling setup, ending when the wager is
   set and the spin button is ready. Press F8 to finish recording.
2. Record the restart-to-main-menu sequence. Press F8 at the main menu.
3. Set the spin point with F9.
4. Set the YoloYen and DOS OCR boxes with F9 at each corner.
5. Choose where to start, set target/deposit/wager, and press **START**.

Press **STOP** to end automation. Your local recording is stored in
`wttg3_workflow.json`, which Git ignores.

## Tests

```powershell
py -3 -m unittest discover -s tests -v
```

Tests also run on Windows through GitHub Actions.

## Disclaimer

This is an unofficial fan utility for a fictional in-game currency. Use it at
your own risk. It is not affiliated with Reflect Studios or the game publisher.

