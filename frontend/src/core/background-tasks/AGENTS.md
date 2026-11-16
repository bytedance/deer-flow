# Background-task queries (`core/background-tasks/`)

A poll that started before a cancel was answered must not undo the cancel. The
mutation drops the thread's background-task reads first, then seeds the
confirmed detail and list entry, then invalidates the list. `core/memory`
follows the same order. Test it with a real `QueryClient`.
