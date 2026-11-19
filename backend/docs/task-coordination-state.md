# Task coordination state

The coordination repository persists a unit of work and its ordered follow-up
inputs. Task IDs are independent of Thread and Run IDs. The Gateway can use
the repository to retain work identity when a later execution moves to a
different agent or thread.

Each call takes an owner resolved by the caller. Task creation deduplicates
requests per owner. Input submission deduplicates requests per task and
assigns consecutive sequence numbers. Reusing a request ID with changed
content returns a conflict. Input request IDs should include the source
namespace if more than one source can submit to a task.

A child inherits its parent's project. Dependencies are immutable and
refer to already-created tasks under the same owner, project, and parent.
A task can start after its dependencies succeed and its parent has started.
Success requires every
owned child to succeed and the accepted result to cover the current input
sequence. Failure can be recorded after all owned children settle.

Mutations within one task tree run under a shared root lock on PostgreSQL and
a short write transaction on SQLite. Callers pass the revision they used to
decide a start, finish, or cancellation. Completion also checks the execution
epoch and input sequence.

Requesting cancellation marks the task and its open descendants as cancelling
and advances their execution epochs in one transaction. Independent
prerequisites keep their state. A running caller can record cancellation
once it has confirmed that the subtree's executions have stopped. The
repository handles work state. Host admission, run control, and artifact
authorization belong to the execution integration.
