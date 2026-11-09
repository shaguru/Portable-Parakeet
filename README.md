# Parakeet Dictation

Parakeet Dictation is a local Windows push-to-talk app. It records from your microphone, transcribes with Parakeet, applies conservative filler cleanup, and pastes the result into the active application.

1. Start it with `python parakeet_dictation.py`.
2. Hold **Win + Alt**, speak, and release either key.
3. The transcription is pasted at the caret.

The app applies a conservative cleanup pass before pasting: standalone hesitation sounds such as “um”, “uh”, “uhm”, “erm”, and “hmm” are removed. It also removes clear filler “like” (for example, “Like, I think…”, “I was, like, thinking…”, or “I like don't know”). Preferences and comparisons such as “I like this” and “That thing is like this” are kept. Ambiguous uses are kept because plain transcripts cannot reliably convey intent or tone. Words containing those letters, such as “umbrella”, are left alone.

The source build carries the Parakeet model and native runtime in the local `models` folder. The portable build carries the same runtime beside the EXE, so the destination computer does not need Python, administrator rights, or an internet connection.

On Windows, the bundled Parakeet command-line worker is launched with its console hidden, so dictation does not open a black command window.

## Portable build

Run `build_portable.ps1` on the development PC. It creates `dist\ParakeetDictation` and `ParakeetDictation-portable.zip`. The ZIP is published as a Release asset because GitHub rejects repository files over 100 MB.

[Download the current portable build from GitHub](https://github.com/shaguru/Portable-Parakeet/releases/tag/v0.1.1).

Extract the ZIP on the destination PC and launch `ParakeetDictation.exe`. Keep the extracted folder together. The package uses the CPU runtime for compatibility with computers that do not have NVIDIA drivers.
