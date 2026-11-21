# YouTube Comments Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and superpowers:test-driven-development. Track verification with the checkboxes below.

**Goal.** Deliver SCR-107 from the [approved design](../specs/2026-11-21-youtube-comments-design.md).

**Architecture.** Resolve numeric report levels at the CLI and always render Transcript. Under the existing source lock, acquire and select a yt-dlp comment snapshot by video ID. Add independently cached comment digests to the existing HTML publication flow.

**Tech stack.** Python 3.12–3.13, the installed yt-dlp, Scribe's Requests API wrapper, unittest and standalone HTML/CSS/JavaScript.

## 1. Report selection

- [ ] Update parser and renderer regressions in `tests/test_summary_detail.py`, `tests/test_summary_html.py` and `tests/test_report_dropdown.py`. Numeric lists preserve order, legacy mixed lists normalize to numbers, and a legacy transcript-only list resolves to zero levels. Every report has one Transcript with available sources.
- [ ] Run the focused report tests to reproduce the old behavior. Update `parse_report_tabs`, the default, renderer and help in `src/scribe.py`. Reuse existing video-summary keys. Run the focused tests again.

## 2. Comment acquisition and snapshots

- [ ] Add mocked extractor and cache tests for anonymous access, explicit-cookie retry, deduplication, partial results, disabled comments, an empty discussion, failed refresh, corrupted artifacts and distinct video IDs sharing source bytes.
- [ ] Add `media_input.fetch_youtube_comments(video_id, args, say)`. Use yt-dlp metadata extraction and safe diagnostics. Return a status and ordered normalized comments.
- [ ] Add `youtube_comments_snapshot(cache, video_id, args)` in `src/scribe.py`. Publish an integrity-checked artifact and a per-video reference under the source lock. Call after output/prerequisite checks, including log-only URL runs. Completed-pair skipping stays ahead of this work.
- [ ] Verify ordinary, forced and summary-only acquisition using mocked URL entry-point runs. Confirm legacy HTML regeneration uses the internal final and leaves an edited export intact.

## 3. Comment digests

- [ ] Test the separate prompt, selected detail, language choice, context budgets, multi-batch and oversized comment handling, source-ID validation, partial coverage, and cache reuse after one failing model request.
- [ ] Add the editable prompt and `youtube_comment_digest(cache, snapshot, language, level, key, model, effort, force=False)` in `src/scribe.py`. Use bounded batches, reusable notes, validated supporting IDs and independent cache keys. Capture Responses usage through the existing mechanism.
- [ ] Verify a failed comment digest leaves the other levels, the original comments and the video report available.

## 4. Standalone HTML and documentation

- [ ] Verify the active Summary panel contains the video and matching comment digest in that order. Verify the Full comments view follows the Transcript source items, contains all retrieved text once, escapes markup and preserves thread order and orphan replies.
- [ ] Render the sections through `summary_html` and add responsive CSS to `src/resources/summary.html`. Reuse the current picker JavaScript and check keyboard and theme behavior.
- [ ] Update `.env.example`, README, usage and project context. Run the full mocked suite and `git diff --check`. Exercise the HTML in Firefox with an isolated fixture. Obtain a code review and record verification in SCR-107 before marking it complete.
