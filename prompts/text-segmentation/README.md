# Text Segmentation Prompt

Version 1 is provider-neutral and produces a sentence proposal for explicit human review.

The runtime source of truth is bundled in the backend package so installed wheels do not depend on a repository checkout:

- [Instruction](../../backend/src/shadowing_video_studio/prompts/segmentation-v1.txt)
- [Output schema](../../backend/src/shadowing_video_studio/prompts/segmentation-v1.schema.json)

Both adapters use this instruction. Codex receives the schema with `--output-schema`; DeepSeek uses JSON Object mode plus the same local strict validation. A provider's structured output promise never replaces application validation.

The proposal contains only `sentences: string[]`. Providers do not assign canonical IDs or confirm the document. The editor assigns stable IDs only when the user applies the reviewed proposal.

Source is limited to 20,000 UTF-16 code units. Results contain 1–500 non-blank sentences, each at most 4,000 UTF-16 code units before trimming. Isolated Unicode surrogates are rejected. Provider output is bounded to 128 KiB. Normal tests use synthetic fixtures and never require live providers.

Treat source as untrusted data. Prompts ask for no tools or code execution; Codex's adapter also disables capabilities and verifies inherited MCP configuration before running. Human review remains necessary: schema-valid output can still segment incorrectly.
