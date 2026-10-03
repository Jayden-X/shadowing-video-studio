# Testing Strategy

## Commands

Full repository check:

```bash
bash scripts/check.sh
```

Backend:

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Frontend:

```bash
cd frontend
npm run typecheck
npm run test
npm run build
```

## Priorities

1. Deterministic text/sentence manipulation.
2. Provider adapter contracts.
3. TTS orchestration and retry/regeneration behavior.
4. Timeline/duration calculations.
5. Video-render command/composition behavior.
6. Critical UI flow smoke tests.

## Rules

- Do not call paid/external AI APIs in normal unit tests.
- Provider responses should be fixture-driven/mocked for deterministic tests.
- Keep at least one explicit local integration/smoke path for Qwen3-TTS and FFmpeg once implemented.
- Qwen3-TTS/model weights are excluded from ordinary GitHub Actions CI.
- Regression fixtures should be small and safe to commit.
- Do not commit large generated videos as test fixtures.
