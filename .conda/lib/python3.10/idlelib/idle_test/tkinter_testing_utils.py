"""Utilities for testing with Tkinter"""
import functools


def run_in_tk_mainloop(delay=1):
    """Decorator for running a test method with a real Tk mainloop.

    This starts a Tk mainloop before running the test, and stops it
    at the end. This is faster and more robust than the common
    alternative method of calling .update() and/or .update_idletasks().

    Test methods using this must be written as generator functions,
    using "yield" to allow the mainloop to process events and "after"
    callbacks, and then continue the test from that point.

    The delay argument is passed into root.after(...) calls as the number
    of ms to wait before passing execution back to the generator function.

    This also assumes that the test class has a .root attribute,
    which is a tkinter.Tk object.

    For example (from test_sidebar.py):

    @run_test_with_tk_mainloop()
    def test_single_empty_input(self):
        self.do_input('\n')
        yield
        self.assert_sidebar_lines_end_with(['>>>', '>>>'])
    """
    def decorator(test_method):
        @functools.wraps(test_method)
        def new_test_method(self):
            test_generator = test_method(self)
            root = self.root
            # Exceptions raised by self.assert...() need to be raised
            # outside of the after() callback in order for the test
            # harness to capture them.
            exception = None
            def after_callback():
                nonlocal exception
                try:
                    next(test_generator)
                except StopIteration:
                    root.quit()
                except Exception as exc:
                    exception = exc
                    root.quit()
                else:
                    # Schedule the Tk mainloop to call this function again,
                    # using a robust method of ensuring that it gets a
                    # chance to process queued events before doing so.
                    # See: https://stackoverflow.com/q/18499082#comment65004099_38817470
                    root.after(delay, root.after_idle, after_callback)
            root.after(0, root.after_idle, after_callback)
            root.mainloop()

            if exception:
                raise exception

        return new_test_method

    return decorator
