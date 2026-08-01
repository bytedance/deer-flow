"""Adapters of the schedule context.

Mostly secondary (driven) adapters -- implementations of the output ports the
domain declares, which the service calls out to:

    scheduled_task_repository.py   owned persistence
    scheduled_run_repository.py    owned persistence
    run_launcher.py                anti-corruption layer over the run runtime
    thread_lookup.py               anti-corruption layer over the thread store

One exception, and the name says so:

    run_completion.py              PRIMARY (inbound) -- the run runtime calls it

It lives here so the context stays in one place rather than beside the other
two primary adapters, which sit next to whatever drives them (the router under
`gateway/routers/schedule/`, the poller under `scheduler/`). Direction is
stated by each module's own first line; a file added here without one is a
file whose direction nobody decided.
"""
