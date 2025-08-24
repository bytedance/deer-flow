"Test colorizer, coverage 99%."
from idlelib import colorizer
from test.support import requires
import unittest
from unittest import mock
from idlelib.idle_test.tkinter_testing_utils import run_in_tk_mainloop

from functools import partial
import textwrap
from tkinter import Tk, Text
from idlelib import config
from idlelib.percolator import Percolator


usercfg = colorizer.idleConf.userCfg
testcfg = {
    'main': config.IdleUserConfParser(''),
    'highlight': config.IdleUserConfParser(''),
    'keys': config.IdleUserConfParser(''),
    'extensions': config.IdleUserConfParser(''),
}

source = textwrap.dedent("""\
    if True: int ('1') # keyword, builtin, string, comment
    elif False: print(0)  # 'string' in comment
    else: float(None)  # if in comment
    if iF + If + IF: 'keyword matching must respect case'
    if'': x or''  # valid keyword-string no-space combinations
    async def f(): await g()
    # Strings should be entirely colored, including quotes.
    'x', '''x''', "x", \"""x\"""
    'abc\\
    def'
    '''abc\\
    def'''
    # All valid prefixes for unicode and byte strings should be colored.
    r'x', u'x', R'x', U'x', f'x', F'x'
    fr'x', Fr'x', fR'x', FR'x', rf'x', rF'x', Rf'x', RF'x'
    b'x',B'x', br'x',Br'x',bR'x',BR'x', rb'x', rB'x',Rb'x',RB'x'
    # Invalid combinations of legal characters should be half colored.
    ur'x', ru'x', uf'x', fu'x', UR'x', ufr'x', rfu'x', xf'x', fx'x'
    match point:
        case (x, 0) as _:
            print(f"X={x}")
        case [_, [_], "_",
                _]:
            pass
        case _ if ("a" if _ else set()): pass
        case _:
            raise ValueError("Not a point _")
    '''
    case _:'''
    "match x:"
    """)


def setUpModule():
    colorizer.idleConf.userCfg = testcfg


def tearDownModule():
    colorizer.idleConf.userCfg = usercfg


class FunctionTest(unittest.TestCase):

    def test_any(self):
        self.assertEqual(colorizer.any('test', ('a', 'b', 'cd')),
                         '(?P<test>a|b|cd)')

    def test_make_pat(self):
        # Tested in more detail by testing prog.
        self.assertTrue(colorizer.make_pat())

    def test_prog(self):
        prog = colorizer.prog
        eq = self.assertEqual
        line = 'def f():\n    print("hello")\n'
        m = prog.search(line)
        eq(m.groupdict()['KEYWORD'], 'def')
        m = prog.search(line, m.end())
        eq(m.groupdict()['SYNC'], '\n')
        m = prog.search(line, m.end())
        eq(m.groupdict()['BUILTIN'], 'print')
        m = prog.search(line, m.end())
        eq(m.groupdict()['STRING'], '"hello"')
        m = prog.search(line, m.end())
        eq(m.groupdict()['SYNC'], '\n')

    def test_idprog(self):
        idprog = colorizer.idprog
        m = idprog.match('nospace')
        self.assertIsNone(m)
        m = idprog.match(' space')
        self.assertEqual(m.group(0), ' space')


class ColorConfigTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        root = cls.root = Tk()
        root.withdraw()
        cls.text = Text(root)

    @classmethod
    def tearDownClass(cls):
        del cls.text
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def test_color_config(self):
        text = self.text
        eq = self.assertEqual
        colorizer.color_config(text)
        # Uses IDLE Classic theme as default.
        eq(text['background'], '#ffffff')
        eq(text['foreground'], '#000000')
        eq(text['selectbackground'], 'gray')
        eq(text['selectforeground'], '#000000')
        eq(text['insertbackground'], 'black')
        eq(text['inactiveselectbackground'], 'gray')


class ColorDelegatorInstantiationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        root = cls.root = Tk()
        root.withdraw()
        cls.text = Text(root)

    @classmethod
    def tearDownClass(cls):
        del cls.text
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def setUp(self):
        self.color = colorizer.ColorDelegator()

    def tearDown(self):
        self.color.close()
        self.text.delete('1.0', 'end')
        self.color.resetcache()
        del self.color

    def test_init(self):
        color = self.color
        self.assertIsInstance(color, colorizer.ColorDelegator)

    def test_init_state(self):
        # init_state() is called during the instantiation of
        # ColorDelegator in setUp().
        color = self.color
        self.assertIsNone(color.after_id)
        self.assertTrue(color.allow_colorizing)
        self.assertFalse(color.colorizing)
        self.assertFalse(color.stop_colorizing)


class ColorDelegatorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        root = cls.root = Tk()
        root.withdraw()
        text = cls.text = Text(root)
        cls.percolator = Percolator(text)
        # Delegator stack = [Delegator(text)]

    @classmethod
    def tearDownClass(cls):
        cls.percolator.close()
        del cls.percolator, cls.text
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def setUp(self):
        self.color = colorizer.ColorDelegator()
        self.percolator.insertfilter(self.color)
        # Calls color.setdelegate(Delegator(text)).

    def tearDown(self):
        self.color.close()
        self.percolator.removefilter(self.color)
        self.text.delete('1.0', 'end')
        self.color.resetcache()
        del self.color

    def test_setdelegate(self):
        # Called in setUp when filter is attached to percolator.
        color = self.color
        self.assertIsInstance(color.delegate, colorizer.Delegator)
        # It is too late to mock notify_range, so test side effect.
        self.assertEqual(self.root.tk.call(
            'after', 'info', color.after_id)[1], 'timer')

    def test_LoadTagDefs(self):
        highlight = partial(config.idleConf.GetHighlight, theme='IDLE Classic')
        for tag, colors in self.color.tagdefs.items():
            with self.subTest(tag=tag):
                self.assertIn('background', colors)
                self.assertIn('foreground', colors)
                if tag not in ('SYNC', 'TODO'):
                    self.assertEqual(colors, highlight(element=tag.lower()))

    def test_config_colors(self):
        text = self.text
        highlight = partial(config.idleConf.GetHighlight, theme='IDLE Classic')
        for tag in self.color.tagdefs:
            for plane in ('background', 'foreground'):
                with self.subTest(tag=tag, plane=plane):
                    if tag in ('SYNC', 'TODO'):
                        self.assertEqual(text.tag_cget(tag, plane), '')
                    else:
                        self.assertEqual(text.tag_cget(tag, plane),
                                         highlight(element=tag.lower())[plane])
        # 'sel' is marked as the highest priority.
        self.assertEqual(text.tag_names()[-1], 'sel')

    @mock.patch.object(colorizer.ColorDelegator, 'notify_range')
    def test_insert(self, mock_notify):
        text = self.text
        # Initial text.
        text.insert('insert', 'foo')
        self.assertEqual(text.get('1.0', 'end'), 'foo\n')
        mock_notify.assert_called_with('1.0', '1.0+3c')
        # Additional text.
        text.insert('insert', 'barbaz')
        self.assertEqual(text.get('1.0', 'end'), 'foobarbaz\n')
        mock_notify.assert_called_with('1.3', '1.3+6c')

    @mock.patch.object(colorizer.ColorDelegator, 'notify_range')
    def test_delete(self, mock_notify):
        text = self.text
        # Initialize text.
        text.insert('insert', 'abcdefghi')
        self.assertEqual(text.get('1.0', 'end'), 'abcdefghi\n')
        # Delete single character.
        text.delete('1.7')
        self.assertEqual(text.get('1.0', 'end'), 'abcdefgi\n')
        mock_notify.assert_called_with('1.7')
        # Delete multiple characters.
        text.delete('1.3', '1.6')
        self.assertEqual(text.get('1.0', 'end'), 'abcgi\n')
        mock_notify.assert_called_with('1.3')

    def test_notify_range(self):
        text = self.text
        color = self.color
        eq = self.assertEqual

        # Colorizing already scheduled.
        save_id = color.after_id
        eq(self.root.tk.call('after', 'info', save_id)[1], 'timer')
        self.assertFalse(color.colorizing)
        self.assertFalse(color.stop_colorizing)
        self.assertTrue(color.allow_colorizing)

        # Coloring scheduled and colorizing in progress.
        color.colorizing = True
        color.notify_range('1.0', 'end')
        self.assertFalse(color.stop_colorizing)
        eq(color.after_id, save_id)

        # No colorizing scheduled and colorizing in progress.
        text.after_cancel(save_id)
        color.after_id = None
        color.notify_range('1.0', '1.0+3c')
        self.assertTrue(color.stop_colorizing)
        self.assertIsNotNone(color.after_id)
        eq(self.root.tk.call('after', 'info', color.after_id)[1], 'timer')
        # New event scheduled.
        self.assertNotEqual(color.after_id, save_id)

        # No colorizing scheduled and colorizing off.
        text.after_cancel(color.after_id)
        color.after_id = None
        color.allow_colorizing = False
        color.notify_range('1.4', '1.4+10c')
        # Nothing scheduled when colorizing is off.
        self.assertIsNone(color.after_id)

    def test_toggle_colorize_event(self):
        color = self.color
        eq = self.assertEqual

        # Starts with colorizing allowed and scheduled.
        self.assertFalse(color.colorizing)
        self.assertFalse(color.stop_colorizing)
        self.assertTrue(color.allow_colorizing)
        eq(self.root.tk.call('after', 'info', color.after_id)[1], 'timer')

        # Toggle colorizing off.
        color.toggle_colorize_event()
        self.assertIsNone(color.after_id)
        self.assertFalse(color.colorizing)
        self.assertFalse(color.stop_colorizing)
        self.assertFalse(color.allow_colorizing)

        # Toggle on while colorizing in progress (doesn't add timer).
        color.colorizing = True
        color.toggle_colorize_event()
        self.assertIsNone(color.after_id)
        self.assertTrue(color.colorizing)
        self.assertFalse(color.stop_colorizing)
        self.assertTrue(color.allow_colorizing)

        # Toggle off while colorizing in progress.
        color.toggle_colorize_event()
        self.assertIsNone(color.after_id)
        self.assertTrue(color.colorizing)
        self.assertTrue(color.stop_colorizing)
        self.assertFalse(color.allow_colorizing)

        # Toggle on while colorizing not in progress.
        color.colorizing = False
        color.toggle_colorize_event()
        eq(self.root.tk.call('after', 'info', color.after_id)[1], 'timer')
        self.assertFalse(color.colorizing)
        self.assertTrue(color.stop_colorizing)
        self.assertTrue(color.allow_colorizing)

    @mock.patch.object(colorizer.ColorDelegator, 'recolorize_main')
    def test_recolorize(self, mock_recmain):
        text = self.text
        color = self.color
        eq = self.assertEqual
        # Call recolorize manually and not scheduled.
        text.after_cancel(color.after_id)

        # No delegate.
        save_delegate = color.delegate
        color.delegate = None
        color.recolorize()
        mock_recmain.assert_not_called()
        color.delegate = save_delegate

        # Toggle off colorizing.
        color.allow_colorizing = False
        color.recolorize()
        mock_recmain.assert_not_called()
        color.allow_colorizing = True

        # Colorizing in progress.
        color.colorizing = True
        color.recolorize()
        mock_recmain.assert_not_called()
        color.colorizing = False

        # Colorizing is done, but not completed, so rescheduled.
        color.recolorize()
        self.assertFalse(color.stop_colorizing)
        self.assertFalse(color.colorizing)
        mock_recmain.assert_called()
        eq(mock_recmain.call_count, 1)
        # Rescheduled when TODO tag still exists.
        eq(self.root.tk.call('after', 'info', color.after_id)[1], 'timer')

        # No changes to text, so no scheduling added.
        text.tag_remove('TODO', '1.0', 'end')
        color.recolorize()
        self.assertFalse(color.stop_colorizing)
        self.assertFalse(color.colorizing)
        mock_recmain.assert_called()
        eq(mock_recmain.call_count, 2)
        self.assertIsNone(color.after_id)

    @mock.patch.object(colorizer.ColorDelegator, 'notify_range')
    def test_recolorize_main(self, mock_notify):
        text = self.text
        color = self.color
        eq = self.assertEqual

        text.insert('insert', source)
        expected = (('1.0', ('KEYWORD',)), ('1.2', ()), ('1.3', ('KEYWORD',)),
                    ('1.7', ()), ('1.9', ('BUILTIN',)), ('1.14', ('STRING',)),
                    ('1.19', ('COMMENT',)),
                    ('2.1', ('KEYWORD',)), ('2.18', ()), ('2.25', ('COMMENT',)),
                    ('3.6', ('BUILTIN',)), ('3.12', ('KEYWORD',)), ('3.21', ('COMMENT',)),
                    ('4.0', ('KEYWORD',)), ('4.3', ()), ('4.6', ()),
                    ('5.2', ('STRING',)), ('5.8', ('KEYWORD',)), ('5.10', ('STRING',)),
                    ('6.0', ('KEYWORD',)), ('6.10', ('DEFINITION',)), ('6.11', ()),
                    ('8.0', ('STRING',)), ('8.4', ()), ('8.5', ('STRING',)),
                    ('8.12', ()), ('8.14', ('STRING',)),
                    ('19.0', ('KEYWORD',)),
                    ('20.4', ('KEYWORD',)), ('20.16', ('KEYWORD',)),# ('20.19', ('KEYWORD',)),
                    #('22.4', ('KEYWORD',)), ('22.10', ('KEYWORD',)), ('22.14', ('KEYWORD',)), ('22.19', ('STRING',)),
                    #('23.12', ('KEYWORD',)),
                    ('24.8', ('KEYWORD',)),
                    ('25.4', ('KEYWORD',)), ('25.9', ('KEYWORD',)),
                    ('25.11', ('KEYWORD',)), ('25.15', ('STRING',)),
                    ('25.19', ('KEYWORD',)), ('25.22', ()),
                    ('25.24', ('KEYWORD',)), ('25.29', ('BUILTIN',)), ('25.37', ('KEYWORD',)),
                    ('26.4', ('KEYWORD',)), ('26.9', ('KEYWORD',)),# ('26.11', ('KEYWORD',)), ('26.14', (),),
                    ('27.25', ('STRING',)), ('27.38', ('STRING',)),
                    ('29.0', ('STRING',)),
                    ('30.1', ('STRING',)),
                    # SYNC at the end of every line.
                    ('1.55', ('SYNC',)), ('2.50', ('SYNC',)), ('3.34', ('SYNC',)),
                   )

        # Nothing marked to do therefore no tags in text.
        text.tag_remove('TODO', '1.0', 'end')
        color.recolorize_main()
        for tag in text.tag_names():
            with self.subTest(tag=tag):
                eq(text.tag_ranges(tag), ())

        # Source marked for processing.
        text.tag_add('TODO', '1.0', 'end')
        # Check some indexes.
        color.recolorize_main()
        for index, expected_tags in expected:
            with self.subTest(index=index):
                eq(text.tag_names(index), expected_tags)

        # Check for some tags for ranges.
        eq(text.tag_nextrange('TODO', '1.0'), ())
        eq(text.tag_nextrange('KEYWORD', '1.0'), ('1.0', '1.2'))
        eq(text.tag_nextrange('COMMENT', '2.0'), ('2.22', '2.43'))
        eq(text.tag_nextrange('SYNC', '2.0'), ('2.43', '3.0'))
        eq(text.tag_nextrange('STRING', '2.0'), ('4.17', '4.53'))
        eq(text.tag_nextrange('STRING', '8.0'), ('8.0', '8.3'))
        eq(text.tag_nextrange('STRING', '8.3'), ('8.5', '8.12'))
        eq(text.tag_nextrange('STRING', '8.12'), ('8.14', '8.17'))
        eq(text.tag_nextrange('STRING', '8.17'), ('8.19', '8.26'))
        eq(text.tag_nextrange('SYNC', '8.0'), ('8.26', '9.0'))
        eq(text.tag_nextrange('SYNC', '30.0'), ('30.10', '32.0'))

    def _assert_highlighting(self, source, tag_ranges):
        """Check highlighting of a given piece of code.

        This inserts just this code into the Text widget. It will then
        check that the resulting highlighting tag ranges exactly match
        those described in the given `tag_ranges` dict.

        Note that the irrelevant tags 'sel', 'TODO' and 'SYNC' are
        ignored.
        """
        text = self.text

        with mock.patch.object(colorizer.ColorDelegator, 'notify_range'):
            text.delete('1.0', 'end-1c')
            text.insert('insert', source)
            text.tag_add('TODO', '1.0', 'end-1c')
            self.color.recolorize_main()

        # Make a dict with highlighting tag ranges in the Text widget.
        text_tag_ranges = {}
        for tag in set(text.tag_names()) - {'sel', 'TODO', 'SYNC'}:
            indexes = [rng.string for rng in text.tag_ranges(tag)]
            for index_pair in zip(indexes[::2], indexes[1::2]):
                text_tag_ranges.setdefault(tag, []).append(index_pair)

        self.assertEqual(text_tag_ranges, tag_ranges)

        with mock.patch.object(colorizer.ColorDelegator, 'notify_range'):
            text.delete('1.0', 'end-1c')

    def test_def_statement(self):
        # empty def
        self._assert_highlighting('def', {'KEYWORD': [('1.0', '1.3')]})

        # def followed by identifier
        self._assert_highlighting('def foo:', {'KEYWORD': [('1.0', '1.3')],
                                               'DEFINITION': [('1.4', '1.7')]})

        # def followed by partial identifier
        self._assert_highlighting('def fo', {'KEYWORD': [('1.0', '1.3')],
                                             'DEFINITION': [('1.4', '1.6')]})

        # def followed by non-keyword
        self._assert_highlighting('def ++', {'KEYWORD': [('1.0', '1.3')]})

    def test_match_soft_keyword(self):
        # empty match
        self._assert_highlighting('match', {'KEYWORD': [('1.0', '1.5')]})

        # match followed by partial identifier
        self._assert_highlighting('match fo', {'KEYWORD': [('1.0', '1.5')]})

        # match followed by identifier and colon
        self._assert_highlighting('match foo:', {'KEYWORD': [('1.0', '1.5')]})

        # match followed by keyword
        self._assert_highlighting('match and', {'KEYWORD': [('1.6', '1.9')]})

        # match followed by builtin with keyword prefix
        self._assert_highlighting('match int:', {'KEYWORD': [('1.0', '1.5')],
                                                 'BUILTIN': [('1.6', '1.9')]})

        # match followed by non-text operator
        self._assert_highlighting('match^', {})
        self._assert_highlighting('match @', {})

        # match followed by colon
        self._assert_highlighting('match :', {})

        # match followed by comma
        self._assert_highlighting('match\t,', {})

        # match followed by a lone underscore
        self._assert_highlighting('match _:', {'KEYWORD': [('1.0', '1.5')]})

    def test_case_soft_keyword(self):
        # empty case
        self._assert_highlighting('case', {'KEYWORD': [('1.0', '1.4')]})

        # case followed by partial identifier
        self._assert_highlighting('case fo', {'KEYWORD': [('1.0', '1.4')]})

        # case followed by identifier and colon
        self._assert_highlighting('case foo:', {'KEYWORD': [('1.0', '1.4')]})

        # case followed by keyword
        self._assert_highlighting('case and', {'KEYWORD': [('1.5', '1.8')]})

        # case followed by builtin with keyword prefix
        self._assert_highlighting('case int:', {'KEYWORD': [('1.0', '1.4')],
                                                'BUILTIN': [('1.5', '1.8')]})

        # case followed by non-text operator
        self._assert_highlighting('case^', {})
        self._assert_highlighting('case @', {})

        # case followed by colon
        self._assert_highlighting('case :', {})

        # case followed by comma
        self._assert_highlighting('case\t,', {})

        # case followed by a lone underscore
        self._assert_highlighting('case _:', {'KEYWORD': [('1.0', '1.4'),
                                                          ('1.5', '1.6')]})

    def test_long_multiline_string(self):
        source = textwrap.dedent('''\
            """a
            b
            c
            d
            e"""
            ''')
        self._assert_highlighting(source, {'STRING': [('1.0', '5.4')]})

    @run_in_tk_mainloop(delay=50)
    def test_incremental_editing(self):
        text = self.text
        eq = self.assertEqual

        # Simulate typing 'inte'. During this, the highlighting should
        # change from normal to keyword to builtin to normal.
        text.insert('insert', 'i')
        yield
        eq(text.tag_nextrange('BUILTIN', '1.0'), ())
        eq(text.tag_nextrange('KEYWORD', '1.0'), ())

        text.insert('insert', 'n')
        yield
        eq(text.tag_nextrange('BUILTIN', '1.0'), ())
        eq(text.tag_nextrange('KEYWORD', '1.0'), ('1.0', '1.2'))

        text.insert('insert', 't')
        yield
        eq(text.tag_nextrange('BUILTIN', '1.0'), ('1.0', '1.3'))
        eq(text.tag_nextrange('KEYWORD', '1.0'), ())

        text.insert('insert', 'e')
        yield
        eq(text.tag_nextrange('BUILTIN', '1.0'), ())
        eq(text.tag_nextrange('KEYWORD', '1.0'), ())

        # Simulate deleting three characters from the end of 'inte'.
        # During this, the highlighting should change from normal to
        # builtin to keyword to normal.
        text.delete('insert-1c', 'insert')
        yield
        eq(text.tag_nextrange('BUILTIN', '1.0'), ('1.0', '1.3'))
        eq(text.tag_nextrange('KEYWORD', '1.0'), ())

        text.delete('insert-1c', 'insert')
        yield
        eq(text.tag_nextrange('BUILTIN', '1.0'), ())
        eq(text.tag_nextrange('KEYWORD', '1.0'), ('1.0', '1.2'))

        text.delete('insert-1c', 'insert')
        yield
        eq(text.tag_nextrange('BUILTIN', '1.0'), ())
        eq(text.tag_nextrange('KEYWORD', '1.0'), ())

    @mock.patch.object(colorizer.ColorDelegator, 'recolorize')
    @mock.patch.object(colorizer.ColorDelegator, 'notify_range')
    def test_removecolors(self, mock_notify, mock_recolorize):
        text = self.text
        color = self.color
        text.insert('insert', source)

        color.recolorize_main()
        # recolorize_main doesn't add these tags.
        text.tag_add("ERROR", "1.0")
        text.tag_add("TODO", "1.0")
        text.tag_add("hit", "1.0")
        for tag in color.tagdefs:
            with self.subTest(tag=tag):
                self.assertNotEqual(text.tag_ranges(tag), ())

        color.removecolors()
        for tag in color.tagdefs:
            with self.subTest(tag=tag):
                self.assertEqual(text.tag_ranges(tag), ())


if __name__ == '__main__':
    unittest.main(verbosity=2)
