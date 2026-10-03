# Runtime Prompts

This directory is for version-controlled prompts used by product AI features.

Rules:
- Keep prompts provider-neutral where practical.
- Separate prompt intent from provider transport/API code.
- Add small input/output fixtures when behavior matters.
- Never place API keys or user-private content in committed prompt files.
- Treat prompt changes that affect product behavior like code changes: review and test them.
