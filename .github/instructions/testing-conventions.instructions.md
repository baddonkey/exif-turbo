---
description: "Use when writing or modifying Python tests. Enforces test naming, structure, and fixture patterns."
applyTo: "tests/**"
---
# Testing Conventions

## Naming

- Name test functions: `test_<unit>_<scenario>_<expected>`
- Name test files: `test_<module>.py`, mirroring the `src/` structure
- Name fixtures descriptively: what they provide, not how

## Structure

Every test follows **Arrange-Act-Assert**:

```python
def test_user_missing_email_raises_validation_error() -> None:
    # Arrange
    invalid_data = {"name": "Alice"}

    # Act / Assert
    with pytest.raises(ValidationError):
        User.from_dict(invalid_data)
```

## Fixtures

- Define fixtures in `conftest.py` at the narrowest scope that makes sense
- Prefer factory fixtures over static data when tests need variations
- Use `tmp_path` for file system tests — never write to the real filesystem

## Mocking

- Mock only at true external boundaries (HTTP, DB, filesystem)
- Prefer fakes and in-memory implementations over `unittest.mock`
- Never mock the unit under test

## Assertions

- One logical assertion per test (multiple `assert` calls are fine if they verify the same behavior)
- Use `pytest.raises` for expected exceptions
- Use `pytest.approx` for floating-point comparisons

## What to avoid

- Tests coupled to implementation details (method call order, internal state)
- Brittle snapshot tests without clear value
- `@pytest.mark.parametrize` with more than ~5 cases — split into focused tests instead
- `sleep()` in tests — use deterministic time control
