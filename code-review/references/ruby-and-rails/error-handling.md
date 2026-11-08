# Error handling (org rule `#EH-CORE-ERROR-HANDLING-RB`)

Rescue at system boundaries, let errors travel through business logic, and separate technical failure from a domain outcome.

### Where to rescue

- Handle unexpected errors only at system boundaries: controllers, background jobs, gRPC handlers, Kafka consumers. Use a boundary handler such as `rescue_from` in a Rails controller, and let the error bubble there so it is logged with its stack trace and converted to a response.
- Do not wrap business logic in `begin`/`rescue` unless the rescue handles a specific recoverable error or adds context.
- Rescue to add context, or to absorb a library that uses exceptions for control flow. Do not rescue just to log: logging alone is not a recovery strategy.
- Wrapping is a re-raise with a semantic type: rescue `ActiveRecord::RecordNotFound` and raise a domain error such as `MissingProjectError`. A re-raise keeps the original exception as its cause.
- Never `rescue Exception`; it catches `NoMemoryError` and `SystemExit` and stops the process from terminating. Rescue `StandardError` or a narrower class.
- Do not rescue only to return `false`, `nil`, or a string. Do not `rescue => e` without re-raising anywhere except the final boundary.

### Cleanup

- Use `ensure`, not `rescue`, when the goal is resetting state or closing a resource. `rescue IOError; file.close` closes the file only on failure and leaks it on success.

### Technical failure versus domain outcome

- Use a raised exception for unexpected, invalid, or technical failure: I/O, network, database, data inconsistency. If nothing raises, the operation succeeded.
- Do not signal technical failure through a return value. `return nil if response.status != 200` is an ambiguous silent failure, and `rescue => e; { success: false, reason: e.message }` is a disguised failure path.
- Use a boolean return value only for a predicate method that answers a state question (`user.admin?`, `valid?`). A boolean is not an operation's success flag.
- Use a structured result object when an operation has several valid domain outcomes, including negative ones that are not failures: `Result = Data.define(:processed, :reason)`. Prefer explicit domain semantics (`:insufficient_balance`) over a generic `success: false`.
- A domain condition is not an error. Collecting `"My domain condition failed"` strings and exposing `failure?` makes the caller check state that an exception would have reported, and makes technical and domain failure indistinguishable.

### Context and accumulation

- Custom errors inherit from a base `ApplicationError`, carry the context that makes them actionable (ids, actor, operation name), and wrap the original.
- Accumulating errors into an array is allowed only for batch operations, validation summaries, and bulk imports. Store the exception objects (`errors << e`), never their messages, so type and stack trace survive.
- Assert error behaviour with `expect { call }.to raise_error(SpecificError)`, check that the message carries the context, and cover the boundary conversion to an HTTP status or job failure. `expect(result[:success]).to be false` and `expect(service).to be_success` are the smells this section exists to remove.
