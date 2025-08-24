"""Tests for distutils.command.install_scripts."""

import os
import unittest

from distutils.command.install_scripts import install_scripts
from distutils.core import Distribution

from distutils.tests import support
from test.support import run_unittest


class InstallScriptsTestCase(support.TempdirManager,
                             support.LoggingSilencer,
                             unittest.TestCase):

    def test_default_settings(self):
        dist = Distribution()
        dist.command_obj["build"] = support.DummyCommand(
            build_scripts="/foo/bar")
        dist.command_obj["install"] = support.DummyCommand(
            install_scripts="/splat/funk",
            force=1,
            skip_build=1,
            )
        cmd = install_scripts(dist)
        self.assertFalse(cmd.force)
        self.assertFalse(cmd.skip_build)
        self.assertIsNone(cmd.build_dir)
        self.assertIsNone(cmd.install_dir)

        cmd.finalize_options()

        self.assertTrue(cmd.force)
        self.assertTrue(cmd.skip_build)
        self.assertEqual(cmd.build_dir, "/foo/bar")
        self.assertEqual(cmd.install_dir, "/splat/funk")

    def test_installation(self):
        source = self.mkdtemp()
        expected = []

        def write_script(name, text):
            expected.append(name)
            f = open(os.path.join(source, name), "w")
            try:
                f.write(text)
            finally:
                f.close()

        write_script("script1.py", ("#! /usr/bin/env python2.3\n"
                                    "# bogus script w/ Python sh-bang\n"
                                    "pass\n"))
        write_script("script2.py", ("#!/usr/bin/python\n"
                                    "# bogus script w/ Python sh-bang\n"
                                    "pass\n"))
        write_script("shell.sh", ("#!/bin/sh\n"
                                  "# bogus shell script w/ sh-bang\n"
                                  "exit 0\n"))

        target = self.mkdtemp()
        dist = Distribution()
        dist.command_obj["build"] = support.DummyCommand(build_scripts=source)
        dist.command_obj["install"] = support.DummyCommand(
            install_scripts=target,
            force=1,
            skip_build=1,
            )
        cmd = install_scripts(dist)
        cmd.finalize_options()
        cmd.run()

        installed = os.listdir(target)
        for name in expected:
            self.assertIn(name, installed)


def test_suite():
    return unittest.makeSuite(InstallScriptsTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
