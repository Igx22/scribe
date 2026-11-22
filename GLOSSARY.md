# Scribe glossary

**Summary** is a condensed account of the content Scribe extracts from a source.
Its detail level ranges from 1 to 10. **Key points** (1/10) captures the essentials,
while **In depth** (10/10) also covers the reasoning, examples and qualifications.

**Transcript** is the text that AI models produce from the speech in a recording.
Scribe uses the final transcript to generate the recording summary.
It stores that version as structured JSON and exports a readable copy as
`.log.md`. Editing the export leaves the text used by `--summary-only` intact.

**Final report** is the single, self-contained `.summary.html` file Scribe generates
from a local recording or a YouTube video. It embeds the summaries, final transcript,
available source views and any included YouTube comments. The file contains all
the content, styles and scripts a browser needs to display it offline.

**Automatic speech recognition (ASR)** converts recorded speech into words. WhisperX Turbo is
Scribe’s default recognizer. Combined modes can produce several transcripts of the
same recording for comparison.

**Speaker diarization** identifies when each distinct voice speaks. Scribe labels
the voices A, B, C and so on. It can attach a name later if the conversation gives
enough evidence to identify the speaker.

**Voice/time anchor** ties a passage of the local transcript to a voice and a time
range. For example, if an anchor assigns 00:12–00:18 to voice A, Scribe can correct
the words in that passage while keeping the voice and time range fixed.

**Text reconciliation (fusion)** is the step where GPT reviews the recognized text
and corrects wording using the available sources. If a passage still fails
validation after retries, Scribe keeps the original wording for that passage.

**Source view** shows what an individual recognizer or diarizer produced before
reconciliation. In the HTML report’s **Transcript** menu, you can compare the
final wording with a recognizer’s original text or inspect the voice intervals.

**Checkpoint** is a saved result from a processing stage. For example, if report
generation fails after transcription finishes, Scribe can reuse the saved
transcript on the next run.
