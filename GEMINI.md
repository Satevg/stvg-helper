# Gemini CLI Mandates - stvg-helper

This file contains absolute mandates for Gemini CLI when working on the `stvg-helper` project.

## Validation Mandates

- **Linting Requirement**: After ANY modification to Python files (`.py`), you MUST execute `make lint`. This ensures `black`, `isort`, and `mypy` standards are maintained.
- **Testing Requirement**: After ANY modification to logic or infrastructure, you MUST execute `make test`.
- **Pre-Deployment**: Before suggesting a "release" or confirming a task as complete, you must ensure both `make lint` and `make test` pass with zero errors.

## Technical Preferences

- **DynamoDB**: Always use `decimal.Decimal` for numerical values when writing to DynamoDB and convert back to `float`/`int` when reading.
- **Coordinates**: Always use normalized coordinates (0.0 to 1.0) for vehicle detection and parking slots to ensure resolution independence.
- **Latency**: Keep manual user-facing handlers (like `parking_handler`) as fast as possible by using `readonly=True` for heatmap operations.
