# Typed data objects (org rule `#EH-TDO-RB`)

- Pass structured data as a typed object rather than a `Hash` in new code: a class (PORO), `Struct`, or `Data`. A hash makes the field set invisible, and a misspelled key returns `nil` instead of raising.
- Use a typed object for a method with many parameters: a nested `Params` type inside the owning class. Few parameters stay keyword arguments. Use one for a multi-field return value and for a value object or DTO.
- Use `Hash` only where the keys genuinely are not known ahead of time.
- Choose the type by what it has to do: `Data.define` for a domain value object that needs immutability and structural equality with minimal behaviour; `Struct.new(..., keyword_init: true)` for a small mutable record, often scoped to one class or a test; a PORO when there are real invariants, a non-trivial constructor or lifecycle, or inheritance.
- Reusable value objects and DTOs live in `app/value_objects/`. A one-off return value may be a nested `Result` type inside the service.
- In tests, instantiate the typed object with test data. If a double is unavoidable, use `instance_double`, because a generic `double` keeps passing after the schema changes.
- A service whose `initialize` takes a `params:` object should assert its type (`raise ArgumentError, "Expected Params" unless params.is_a?(Params)`) rather than trusting the caller.
