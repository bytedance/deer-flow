class PermanentNotificationError(RuntimeError):
    """A notification cannot ever be delivered without external state changing."""
