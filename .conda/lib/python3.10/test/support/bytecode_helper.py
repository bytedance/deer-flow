"""bytecode_helper - support tools for testing correct bytecode generation"""

import unittest
import dis
import io

_UNSPECIFIED = object()

class BytecodeTestCase(unittest.TestCase):
    """Custom assertion methods for inspecting bytecode."""

    def get_disassembly_as_string(self, co):
        s = io.StringIO()
        dis.dis(co, file=s)
        return s.getvalue()

    def assertInBytecode(self, x, opname, argval=_UNSPECIFIED):
        """Returns instr if opname is found, otherwise throws AssertionError"""
        for instr in dis.get_instructions(x):
            if instr.opname == opname:
                if argval is _UNSPECIFIED or instr.argval == argval:
                    return instr
        disassembly = self.get_disassembly_as_string(x)
        if argval is _UNSPECIFIED:
            msg = '%s not found in bytecode:\n%s' % (opname, disassembly)
        else:
            msg = '(%s,%r) not found in bytecode:\n%s'
            msg = msg % (opname, argval, disassembly)
        self.fail(msg)

    def assertNotInBytecode(self, x, opname, argval=_UNSPECIFIED):
        """Throws AssertionError if opname is found"""
        for instr in dis.get_instructions(x):
            if instr.opname == opname:
                disassembly = self.get_disassembly_as_string(x)
                if argval is _UNSPECIFIED:
                    msg = '%s occurs in bytecode:\n%s' % (opname, disassembly)
                    self.fail(msg)
                elif instr.argval == argval:
                    msg = '(%s,%r) occurs in bytecode:\n%s'
                    msg = msg % (opname, argval, disassembly)
                    self.fail(msg)
