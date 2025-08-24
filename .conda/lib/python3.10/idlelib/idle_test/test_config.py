"""Test config, coverage 93%.
(100% for IdleConfParser, IdleUserConfParser*, ConfigChanges).
* Exception is OSError clause in Save method.
Much of IdleConf is also exercised by ConfigDialog and test_configdialog.
"""
from idlelib import config
import sys
import os
import tempfile
from test.support import captured_stderr, findfile
import unittest
from unittest import mock
import idlelib
from idlelib.idle_test.mock_idle import Func

# Tests should not depend on fortuitous user configurations.
# They must not affect actual user .cfg files.
# Replace user parsers with empty parsers that cannot be saved
# due to getting '' as the filename when created.

idleConf = config.idleConf
usercfg = idleConf.userCfg
testcfg = {}
usermain = testcfg['main'] = config.IdleUserConfParser('')
userhigh = testcfg['highlight'] = config.IdleUserConfParser('')
userkeys = testcfg['keys'] = config.IdleUserConfParser('')
userextn = testcfg['extensions'] = config.IdleUserConfParser('')

def setUpModule():
    idleConf.userCfg = testcfg
    idlelib.testing = True

def tearDownModule():
    idleConf.userCfg = usercfg
    idlelib.testing = False


class IdleConfParserTest(unittest.TestCase):
    """Test that IdleConfParser works"""

    config = """
        [one]
        one = false
        two = true
        three = 10

        [two]
        one = a string
        two = true
        three = false
    """

    def test_get(self):
        parser = config.IdleConfParser('')
        parser.read_string(self.config)
        eq = self.assertEqual

        # Test with type argument.
        self.assertIs(parser.Get('one', 'one', type='bool'), False)
        self.assertIs(parser.Get('one', 'two', type='bool'), True)
        eq(parser.Get('one', 'three', type='int'), 10)
        eq(parser.Get('two', 'one'), 'a string')
        self.assertIs(parser.Get('two', 'two', type='bool'), True)
        self.assertIs(parser.Get('two', 'three', type='bool'), False)

        # Test without type should fallback to string.
        eq(parser.Get('two', 'two'), 'true')
        eq(parser.Get('two', 'three'), 'false')

        # If option not exist, should return None, or default.
        self.assertIsNone(parser.Get('not', 'exist'))
        eq(parser.Get('not', 'exist', default='DEFAULT'), 'DEFAULT')

    def test_get_option_list(self):
        parser = config.IdleConfParser('')
        parser.read_string(self.config)
        get_list = parser.GetOptionList
        self.assertCountEqual(get_list('one'), ['one', 'two', 'three'])
        self.assertCountEqual(get_list('two'), ['one', 'two', 'three'])
        self.assertEqual(get_list('not exist'), [])

    def test_load_nothing(self):
        parser = config.IdleConfParser('')
        parser.Load()
        self.assertEqual(parser.sections(), [])

    def test_load_file(self):
        # Borrow test/cfgparser.1 from test_configparser.
        config_path = findfile('cfgparser.1')
        parser = config.IdleConfParser(config_path)
        parser.Load()

        self.assertEqual(parser.Get('Foo Bar', 'foo'), 'newbar')
        self.assertEqual(parser.GetOptionList('Foo Bar'), ['foo'])


class IdleUserConfParserTest(unittest.TestCase):
    """Test that IdleUserConfParser works"""

    def new_parser(self, path=''):
        return config.IdleUserConfParser(path)

    def test_set_option(self):
        parser = self.new_parser()
        parser.add_section('Foo')
        # Setting new option in existing section should return True.
        self.assertTrue(parser.SetOption('Foo', 'bar', 'true'))
        # Setting existing option with same value should return False.
        self.assertFalse(parser.SetOption('Foo', 'bar', 'true'))
        # Setting exiting option with new value should return True.
        self.assertTrue(parser.SetOption('Foo', 'bar', 'false'))
        self.assertEqual(parser.Get('Foo', 'bar'), 'false')

        # Setting option in new section should create section and return True.
        self.assertTrue(parser.SetOption('Bar', 'bar', 'true'))
        self.assertCountEqual(parser.sections(), ['Bar', 'Foo'])
        self.assertEqual(parser.Get('Bar', 'bar'), 'true')

    def test_remove_option(self):
        parser = self.new_parser()
        parser.AddSection('Foo')
        parser.SetOption('Foo', 'bar', 'true')

        self.assertTrue(parser.RemoveOption('Foo', 'bar'))
        self.assertFalse(parser.RemoveOption('Foo', 'bar'))
        self.assertFalse(parser.RemoveOption('Not', 'Exist'))

    def test_add_section(self):
        parser = self.new_parser()
        self.assertEqual(parser.sections(), [])

        # Should not add duplicate section.
        # Configparser raises DuplicateError, IdleParser not.
        parser.AddSection('Foo')
        parser.AddSection('Foo')
        parser.AddSection('Bar')
        self.assertCountEqual(parser.sections(), ['Bar', 'Foo'])

    def test_remove_empty_sections(self):
        parser = self.new_parser()

        parser.AddSection('Foo')
        parser.AddSection('Bar')
        parser.SetOption('Idle', 'name', 'val')
        self.assertCountEqual(parser.sections(), ['Bar', 'Foo', 'Idle'])
        parser.RemoveEmptySections()
        self.assertEqual(parser.sections(), ['Idle'])

    def test_is_empty(self):
        parser = self.new_parser()

        parser.AddSection('Foo')
        parser.AddSection('Bar')
        self.assertTrue(parser.IsEmpty())
        self.assertEqual(parser.sections(), [])

        parser.SetOption('Foo', 'bar', 'false')
        parser.AddSection('Bar')
        self.assertFalse(parser.IsEmpty())
        self.assertCountEqual(parser.sections(), ['Foo'])

    def test_save(self):
        with tempfile.TemporaryDirectory() as tdir:
            path = os.path.join(tdir, 'test.cfg')
            parser = self.new_parser(path)
            parser.AddSection('Foo')
            parser.SetOption('Foo', 'bar', 'true')

            # Should save to path when config is not empty.
            self.assertFalse(os.path.exists(path))
            parser.Save()
            self.assertTrue(os.path.exists(path))

            # Should remove the file from disk when config is empty.
            parser.remove_section('Foo')
            parser.Save()
            self.assertFalse(os.path.exists(path))


class IdleConfTest(unittest.TestCase):
    """Test for idleConf"""

    @classmethod
    def setUpClass(cls):
        cls.config_string = {}

        conf = config.IdleConf(_utest=True)
        if __name__ != '__main__':
            idle_dir = os.path.dirname(__file__)
        else:
            idle_dir = os.path.abspath(sys.path[0])
        for ctype in conf.config_types:
            config_path = os.path.join(idle_dir, '../config-%s.def' % ctype)
            with open(config_path, 'r') as f:
                cls.config_string[ctype] = f.read()

        cls.orig_warn = config._warn
        config._warn = Func()

    @classmethod
    def tearDownClass(cls):
        config._warn = cls.orig_warn

    def new_config(self, _utest=False):
        return config.IdleConf(_utest=_utest)

    def mock_config(self):
        """Return a mocked idleConf

        Both default and user config used the same config-*.def
        """
        conf = config.IdleConf(_utest=True)
        for ctype in conf.config_types:
            conf.defaultCfg[ctype] = config.IdleConfParser('')
            conf.defaultCfg[ctype].read_string(self.config_string[ctype])
            conf.userCfg[ctype] = config.IdleUserConfParser('')
            conf.userCfg[ctype].read_string(self.config_string[ctype])

        return conf

    @unittest.skipIf(sys.platform.startswith('win'), 'this is test for unix system')
    def test_get_user_cfg_dir_unix(self):
        # Test to get user config directory under unix.
        conf = self.new_config(_utest=True)

        # Check normal way should success
        with mock.patch('os.path.expanduser', return_value='/home/foo'):
            with mock.patch('os.path.exists', return_value=True):
                self.assertEqual(conf.GetUserCfgDir(), '/home/foo/.idlerc')

        # Check os.getcwd should success
        with mock.patch('os.path.expanduser', return_value='~'):
            with mock.patch('os.getcwd', return_value='/home/foo/cpython'):
                with mock.patch('os.mkdir'):
                    self.assertEqual(conf.GetUserCfgDir(),
                                     '/home/foo/cpython/.idlerc')

        # Check user dir not exists and created failed should raise SystemExit
        with mock.patch('os.path.join', return_value='/path/not/exists'):
            with self.assertRaises(SystemExit):
                with self.assertRaises(FileNotFoundError):
                    conf.GetUserCfgDir()

    @unittest.skipIf(not sys.platform.startswith('win'), 'this is test for Windows system')
    def test_get_user_cfg_dir_windows(self):
        # Test to get user config directory under Windows.
        conf = self.new_config(_utest=True)

        # Check normal way should success
        with mock.patch('os.path.expanduser', return_value='C:\\foo'):
            with mock.patch('os.path.exists', return_value=True):
                self.assertEqual(conf.GetUserCfgDir(), 'C:\\foo\\.idlerc')

        # Check os.getcwd should success
        with mock.patch('os.path.expanduser', return_value='~'):
            with mock.patch('os.getcwd', return_value='C:\\foo\\cpython'):
                with mock.patch('os.mkdir'):
                    self.assertEqual(conf.GetUserCfgDir(),
                                     'C:\\foo\\cpython\\.idlerc')

        # Check user dir not exists and created failed should raise SystemExit
        with mock.patch('os.path.join', return_value='/path/not/exists'):
            with self.assertRaises(SystemExit):
                with self.assertRaises(FileNotFoundError):
                    conf.GetUserCfgDir()

    def test_create_config_handlers(self):
        conf = self.new_config(_utest=True)

        # Mock out idle_dir
        idle_dir = '/home/foo'
        with mock.patch.dict({'__name__': '__foo__'}):
            with mock.patch('os.path.dirname', return_value=idle_dir):
                conf.CreateConfigHandlers()

        # Check keys are equal
        self.assertCountEqual(conf.defaultCfg.keys(), conf.config_types)
        self.assertCountEqual(conf.userCfg.keys(), conf.config_types)

        # Check conf parser are correct type
        for default_parser in conf.defaultCfg.values():
            self.assertIsInstance(default_parser, config.IdleConfParser)
        for user_parser in conf.userCfg.values():
            self.assertIsInstance(user_parser, config.IdleUserConfParser)

        # Check config path are correct
        for cfg_type, parser in conf.defaultCfg.items():
            self.assertEqual(parser.file,
                             os.path.join(idle_dir, f'config-{cfg_type}.def'))
        for cfg_type, parser in conf.userCfg.items():
            self.assertEqual(parser.file,
                             os.path.join(conf.userdir or '#', f'config-{cfg_type}.cfg'))

    def test_load_cfg_files(self):
        conf = self.new_config(_utest=True)

        # Borrow test/cfgparser.1 from test_configparser.
        config_path = findfile('cfgparser.1')
        conf.defaultCfg['foo'] = config.IdleConfParser(config_path)
        conf.userCfg['foo'] = config.IdleUserConfParser(config_path)

        # Load all config from path
        conf.LoadCfgFiles()

        eq = self.assertEqual

        # Check defaultCfg is loaded
        eq(conf.defaultCfg['foo'].Get('Foo Bar', 'foo'), 'newbar')
        eq(conf.defaultCfg['foo'].GetOptionList('Foo Bar'), ['foo'])

        # Check userCfg is loaded
        eq(conf.userCfg['foo'].Get('Foo Bar', 'foo'), 'newbar')
        eq(conf.userCfg['foo'].GetOptionList('Foo Bar'), ['foo'])

    def test_save_user_cfg_files(self):
        conf = self.mock_config()

        with mock.patch('idlelib.config.IdleUserConfParser.Save') as m:
            conf.SaveUserCfgFiles()
            self.assertEqual(m.call_count, len(conf.userCfg))

    def test_get_option(self):
        conf = self.mock_config()

        eq = self.assertEqual
        eq(conf.GetOption('main', 'EditorWindow', 'width'), '80')
        eq(conf.GetOption('main', 'EditorWindow', 'width', type='int'), 80)
        with mock.patch('idlelib.config._warn') as _warn:
            eq(conf.GetOption('main', 'EditorWindow', 'font', type='int'), None)
            eq(conf.GetOption('main', 'EditorWindow', 'NotExists'), None)
            eq(conf.GetOption('main', 'EditorWindow', 'NotExists', default='NE'), 'NE')
            eq(_warn.call_count, 4)

    def test_set_option(self):
        conf = self.mock_config()

        conf.SetOption('main', 'Foo', 'bar', 'newbar')
        self.assertEqual(conf.GetOption('main', 'Foo', 'bar'), 'newbar')

    def test_get_section_list(self):
        conf = self.mock_config()

        self.assertCountEqual(
            conf.GetSectionList('default', 'main'),
            ['General', 'EditorWindow', 'PyShell', 'Indent', 'Theme',
             'Keys', 'History', 'HelpFiles'])
        self.assertCountEqual(
            conf.GetSectionList('user', 'main'),
            ['General', 'EditorWindow', 'PyShell', 'Indent', 'Theme',
             'Keys', 'History', 'HelpFiles'])

        with self.assertRaises(config.InvalidConfigSet):
            conf.GetSectionList('foobar', 'main')
        with self.assertRaises(config.InvalidConfigType):
            conf.GetSectionList('default', 'notexists')

    def test_get_highlight(self):
        conf = self.mock_config()

        eq = self.assertEqual
        eq(conf.GetHighlight('IDLE Classic', 'normal'), {'foreground': '#000000',
                                                         'background': '#ffffff'})

        # Test cursor (this background should be normal-background)
        eq(conf.GetHighlight('IDLE Classic', 'cursor'), {'foreground': 'black',
                                                         'background': '#ffffff'})

        # Test get user themes
        conf.SetOption('highlight', 'Foobar', 'normal-foreground', '#747474')
        conf.SetOption('highlight', 'Foobar', 'normal-background', '#171717')
        with mock.patch('idlelib.config._warn'):
            eq(conf.GetHighlight('Foobar', 'normal'), {'foreground': '#747474',
                                                       'background': '#171717'})

    def test_get_theme_dict(self):
        # TODO: finish.
        conf = self.mock_config()

        # These two should be the same
        self.assertEqual(
            conf.GetThemeDict('default', 'IDLE Classic'),
            conf.GetThemeDict('user', 'IDLE Classic'))

        with self.assertRaises(config.InvalidTheme):
            conf.GetThemeDict('bad', 'IDLE Classic')

    def test_get_current_theme_and_keys(self):
        conf = self.mock_config()

        self.assertEqual(conf.CurrentTheme(), conf.current_colors_and_keys('Theme'))
        self.assertEqual(conf.CurrentKeys(), conf.current_colors_and_keys('Keys'))

    def test_current_colors_and_keys(self):
        conf = self.mock_config()

        self.assertEqual(conf.current_colors_and_keys('Theme'), 'IDLE Classic')

    def test_default_keys(self):
        current_platform = sys.platform
        conf = self.new_config(_utest=True)

        sys.platform = 'win32'
        self.assertEqual(conf.default_keys(), 'IDLE Classic Windows')

        sys.platform = 'darwin'
        self.assertEqual(conf.default_keys(), 'IDLE Classic OSX')

        sys.platform = 'some-linux'
        self.assertEqual(conf.default_keys(), 'IDLE Modern Unix')

        # Restore platform
        sys.platform = current_platform

    def test_get_extensions(self):
        userextn.read_string('''
            [ZzDummy]
            enable = True
            [DISABLE]
            enable = False
            ''')
        eq = self.assertEqual
        iGE = idleConf.GetExtensions
        eq(iGE(shell_only=True), [])
        eq(iGE(), ['ZzDummy'])
        eq(iGE(editor_only=True), ['ZzDummy'])
        eq(iGE(active_only=False), ['ZzDummy', 'DISABLE'])
        eq(iGE(active_only=False, editor_only=True), ['ZzDummy', 'DISABLE'])
        userextn.remove_section('ZzDummy')
        userextn.remove_section('DISABLE')


    def test_remove_key_bind_names(self):
        conf = self.mock_config()

        self.assertCountEqual(
            conf.RemoveKeyBindNames(conf.GetSectionList('default', 'extensions')),
            ['AutoComplete', 'CodeContext', 'FormatParagraph', 'ParenMatch', 'ZzDummy'])

    def test_get_extn_name_for_event(self):
        userextn.read_string('''
            [ZzDummy]
            enable = True
            ''')
        eq = self.assertEqual
        eq(idleConf.GetExtnNameForEvent('z-in'), 'ZzDummy')
        eq(idleConf.GetExtnNameForEvent('z-out'), None)
        userextn.remove_section('ZzDummy')

    def test_get_extension_keys(self):
        userextn.read_string('''
            [ZzDummy]
            enable = True
            ''')
        self.assertEqual(idleConf.GetExtensionKeys('ZzDummy'),
           {'<<z-in>>': ['<Control-Shift-KeyRelease-Insert>']})
        userextn.remove_section('ZzDummy')
# need option key test
##        key = ['<Option-Key-2>'] if sys.platform == 'darwin' else ['<Alt-Key-2>']
##        eq(conf.GetExtensionKeys('ZoomHeight'), {'<<zoom-height>>': key})

    def test_get_extension_bindings(self):
        userextn.read_string('''
            [ZzDummy]
            enable = True
            ''')
        eq = self.assertEqual
        iGEB = idleConf.GetExtensionBindings
        eq(iGEB('NotExists'), {})
        expect = {'<<z-in>>': ['<Control-Shift-KeyRelease-Insert>'],
                  '<<z-out>>': ['<Control-Shift-KeyRelease-Delete>']}
        eq(iGEB('ZzDummy'), expect)
        userextn.remove_section('ZzDummy')

    def test_get_keybinding(self):
        conf = self.mock_config()

        eq = self.assertEqual
        eq(conf.GetKeyBinding('IDLE Modern Unix', '<<copy>>'),
            ['<Control-Shift-Key-C>', '<Control-Key-Insert>'])
        eq(conf.GetKeyBinding('IDLE Classic Unix', '<<copy>>'),
            ['<Alt-Key-w>', '<Meta-Key-w>'])
        eq(conf.GetKeyBinding('IDLE Classic Windows', '<<copy>>'),
            ['<Control-Key-c>', '<Control-Key-C>'])
        eq(conf.GetKeyBinding('IDLE Classic Mac', '<<copy>>'), ['<Command-Key-c>'])
        eq(conf.GetKeyBinding('IDLE Classic OSX', '<<copy>>'), ['<Command-Key-c>'])

        # Test keybinding not exists
        eq(conf.GetKeyBinding('NOT EXISTS', '<<copy>>'), [])
        eq(conf.GetKeyBinding('IDLE Modern Unix', 'NOT EXISTS'), [])

    def test_get_current_keyset(self):
        current_platform = sys.platform
        conf = self.mock_config()

        # Ensure that platform isn't darwin
        sys.platform = 'some-linux'
        self.assertEqual(conf.GetCurrentKeySet(), conf.GetKeySet(conf.CurrentKeys()))

        # This should not be the same, since replace <Alt- to <Option-.
        # Above depended on config-extensions.def having Alt keys,
        # which is no longer true.
        # sys.platform = 'darwin'
        # self.assertNotEqual(conf.GetCurrentKeySet(), conf.GetKeySet(conf.CurrentKeys()))

        # Restore platform
        sys.platform = current_platform

    def test_get_keyset(self):
        conf = self.mock_config()

        # Conflict with key set, should be disable to ''
        conf.defaultCfg['extensions'].add_section('Foobar')
        conf.defaultCfg['extensions'].add_section('Foobar_cfgBindings')
        conf.defaultCfg['extensions'].set('Foobar', 'enable', 'True')
        conf.defaultCfg['extensions'].set('Foobar_cfgBindings', 'newfoo', '<Key-F3>')
        self.assertEqual(conf.GetKeySet('IDLE Modern Unix')['<<newfoo>>'], '')

    def test_is_core_binding(self):
        # XXX: Should move out the core keys to config file or other place
        conf = self.mock_config()

        self.assertTrue(conf.IsCoreBinding('copy'))
        self.assertTrue(conf.IsCoreBinding('cut'))
        self.assertTrue(conf.IsCoreBinding('del-word-right'))
        self.assertFalse(conf.IsCoreBinding('not-exists'))

    def test_extra_help_source_list(self):
        # Test GetExtraHelpSourceList and GetAllExtraHelpSourcesList in same
        # place to prevent prepare input data twice.
        conf = self.mock_config()

        # Test default with no extra help source
        self.assertEqual(conf.GetExtraHelpSourceList('default'), [])
        self.assertEqual(conf.GetExtraHelpSourceList('user'), [])
        with self.assertRaises(config.InvalidConfigSet):
            self.assertEqual(conf.GetExtraHelpSourceList('bad'), [])
        self.assertCountEqual(
            conf.GetAllExtraHelpSourcesList(),
            conf.GetExtraHelpSourceList('default') + conf.GetExtraHelpSourceList('user'))

        # Add help source to user config
        conf.userCfg['main'].SetOption('HelpFiles', '4', 'Python;https://python.org')  # This is bad input
        conf.userCfg['main'].SetOption('HelpFiles', '3', 'Python:https://python.org')  # This is bad input
        conf.userCfg['main'].SetOption('HelpFiles', '2', 'Pillow;https://pillow.readthedocs.io/en/latest/')
        conf.userCfg['main'].SetOption('HelpFiles', '1', 'IDLE;C:/Programs/Python36/Lib/idlelib/help.html')
        self.assertEqual(conf.GetExtraHelpSourceList('user'),
                         [('IDLE', 'C:/Programs/Python36/Lib/idlelib/help.html', '1'),
                          ('Pillow', 'https://pillow.readthedocs.io/en/latest/', '2'),
                          ('Python', 'https://python.org', '4')])
        self.assertCountEqual(
            conf.GetAllExtraHelpSourcesList(),
            conf.GetExtraHelpSourceList('default') + conf.GetExtraHelpSourceList('user'))

    def test_get_font(self):
        from test.support import requires
        from tkinter import Tk
        from tkinter.font import Font
        conf = self.mock_config()

        requires('gui')
        root = Tk()
        root.withdraw()

        f = Font.actual(Font(name='TkFixedFont', exists=True, root=root))
        self.assertEqual(
            conf.GetFont(root, 'main', 'EditorWindow'),
            (f['family'], 10 if f['size'] <= 0 else f['size'], f['weight']))

        # Cleanup root
        root.destroy()
        del root

    def test_get_core_keys(self):
        conf = self.mock_config()

        eq = self.assertEqual
        eq(conf.GetCoreKeys()['<<center-insert>>'], ['<Control-l>'])
        eq(conf.GetCoreKeys()['<<copy>>'], ['<Control-c>', '<Control-C>'])
        eq(conf.GetCoreKeys()['<<history-next>>'], ['<Alt-n>'])
        eq(conf.GetCoreKeys('IDLE Classic Windows')['<<center-insert>>'],
           ['<Control-Key-l>', '<Control-Key-L>'])
        eq(conf.GetCoreKeys('IDLE Classic OSX')['<<copy>>'], ['<Command-Key-c>'])
        eq(conf.GetCoreKeys('IDLE Classic Unix')['<<history-next>>'],
           ['<Alt-Key-n>', '<Meta-Key-n>'])
        eq(conf.GetCoreKeys('IDLE Modern Unix')['<<history-next>>'],
            ['<Alt-Key-n>', '<Meta-Key-n>'])


class CurrentColorKeysTest(unittest.TestCase):
    """ Test colorkeys function with user config [Theme] and [Keys] patterns.

        colorkeys = config.IdleConf.current_colors_and_keys
        Test all patterns written by IDLE and some errors
        Item 'default' should really be 'builtin' (versus 'custom).
    """
    colorkeys = idleConf.current_colors_and_keys
    default_theme = 'IDLE Classic'
    default_keys = idleConf.default_keys()

    def test_old_builtin_theme(self):
        # On initial installation, user main is blank.
        self.assertEqual(self.colorkeys('Theme'), self.default_theme)
        # For old default, name2 must be blank.
        usermain.read_string('''
            [Theme]
            default = True
            ''')
        # IDLE omits 'name' for default old builtin theme.
        self.assertEqual(self.colorkeys('Theme'), self.default_theme)
        # IDLE adds 'name' for non-default old builtin theme.
        usermain['Theme']['name'] = 'IDLE New'
        self.assertEqual(self.colorkeys('Theme'), 'IDLE New')
        # Erroneous non-default old builtin reverts to default.
        usermain['Theme']['name'] = 'non-existent'
        self.assertEqual(self.colorkeys('Theme'), self.default_theme)
        usermain.remove_section('Theme')

    def test_new_builtin_theme(self):
        # IDLE writes name2 for new builtins.
        usermain.read_string('''
            [Theme]
            default = True
            name2 = IDLE Dark
            ''')
        self.assertEqual(self.colorkeys('Theme'), 'IDLE Dark')
        # Leftover 'name', not removed, is ignored.
        usermain['Theme']['name'] = 'IDLE New'
        self.assertEqual(self.colorkeys('Theme'), 'IDLE Dark')
        # Erroneous non-default new builtin reverts to default.
        usermain['Theme']['name2'] = 'non-existent'
        self.assertEqual(self.colorkeys('Theme'), self.default_theme)
        usermain.remove_section('Theme')

    def test_user_override_theme(self):
        # Erroneous custom name (no definition) reverts to default.
        usermain.read_string('''
            [Theme]
            default = False
            name = Custom Dark
            ''')
        self.assertEqual(self.colorkeys('Theme'), self.default_theme)
        # Custom name is valid with matching Section name.
        userhigh.read_string('[Custom Dark]\na=b')
        self.assertEqual(self.colorkeys('Theme'), 'Custom Dark')
        # Name2 is ignored.
        usermain['Theme']['name2'] = 'non-existent'
        self.assertEqual(self.colorkeys('Theme'), 'Custom Dark')
        usermain.remove_section('Theme')
        userhigh.remove_section('Custom Dark')

    def test_old_builtin_keys(self):
        # On initial installation, user main is blank.
        self.assertEqual(self.colorkeys('Keys'), self.default_keys)
        # For old default, name2 must be blank, name is always used.
        usermain.read_string('''
            [Keys]
            default = True
            name = IDLE Classic Unix
            ''')
        self.assertEqual(self.colorkeys('Keys'), 'IDLE Classic Unix')
        # Erroneous non-default old builtin reverts to default.
        usermain['Keys']['name'] = 'non-existent'
        self.assertEqual(self.colorkeys('Keys'), self.default_keys)
        usermain.remove_section('Keys')

    def test_new_builtin_keys(self):
        # IDLE writes name2 for new builtins.
        usermain.read_string('''
            [Keys]
            default = True
            name2 = IDLE Modern Unix
            ''')
        self.assertEqual(self.colorkeys('Keys'), 'IDLE Modern Unix')
        # Leftover 'name', not removed, is ignored.
        usermain['Keys']['name'] = 'IDLE Classic Unix'
        self.assertEqual(self.colorkeys('Keys'), 'IDLE Modern Unix')
        # Erroneous non-default new builtin reverts to default.
        usermain['Keys']['name2'] = 'non-existent'
        self.assertEqual(self.colorkeys('Keys'), self.default_keys)
        usermain.remove_section('Keys')

    def test_user_override_keys(self):
        # Erroneous custom name (no definition) reverts to default.
        usermain.read_string('''
            [Keys]
            default = False
            name = Custom Keys
            ''')
        self.assertEqual(self.colorkeys('Keys'), self.default_keys)
        # Custom name is valid with matching Section name.
        userkeys.read_string('[Custom Keys]\na=b')
        self.assertEqual(self.colorkeys('Keys'), 'Custom Keys')
        # Name2 is ignored.
        usermain['Keys']['name2'] = 'non-existent'
        self.assertEqual(self.colorkeys('Keys'), 'Custom Keys')
        usermain.remove_section('Keys')
        userkeys.remove_section('Custom Keys')


class ChangesTest(unittest.TestCase):

    empty = {'main':{}, 'highlight':{}, 'keys':{}, 'extensions':{}}

    def load(self):  # Test_add_option verifies that this works.
        changes = self.changes
        changes.add_option('main', 'Msec', 'mitem', 'mval')
        changes.add_option('highlight', 'Hsec', 'hitem', 'hval')
        changes.add_option('keys', 'Ksec', 'kitem', 'kval')
        return changes

    loaded = {'main': {'Msec': {'mitem': 'mval'}},
              'highlight': {'Hsec': {'hitem': 'hval'}},
              'keys': {'Ksec': {'kitem':'kval'}},
              'extensions': {}}

    def setUp(self):
        self.changes = config.ConfigChanges()

    def test_init(self):
        self.assertEqual(self.changes, self.empty)

    def test_add_option(self):
        changes = self.load()
        self.assertEqual(changes, self.loaded)
        changes.add_option('main', 'Msec', 'mitem', 'mval')
        self.assertEqual(changes, self.loaded)

    def test_save_option(self):  # Static function does not touch changes.
        save_option = self.changes.save_option
        self.assertTrue(save_option('main', 'Indent', 'what', '0'))
        self.assertFalse(save_option('main', 'Indent', 'what', '0'))
        self.assertEqual(usermain['Indent']['what'], '0')

        self.assertTrue(save_option('main', 'Indent', 'use-spaces', '0'))
        self.assertEqual(usermain['Indent']['use-spaces'], '0')
        self.assertTrue(save_option('main', 'Indent', 'use-spaces', '1'))
        self.assertFalse(usermain.has_option('Indent', 'use-spaces'))
        usermain.remove_section('Indent')

    def test_save_added(self):
        changes = self.load()
        self.assertTrue(changes.save_all())
        self.assertEqual(usermain['Msec']['mitem'], 'mval')
        self.assertEqual(userhigh['Hsec']['hitem'], 'hval')
        self.assertEqual(userkeys['Ksec']['kitem'], 'kval')
        changes.add_option('main', 'Msec', 'mitem', 'mval')
        self.assertFalse(changes.save_all())
        usermain.remove_section('Msec')
        userhigh.remove_section('Hsec')
        userkeys.remove_section('Ksec')

    def test_save_help(self):
        # Any change to HelpFiles overwrites entire section.
        changes = self.changes
        changes.save_option('main', 'HelpFiles', 'IDLE', 'idledoc')
        changes.add_option('main', 'HelpFiles', 'ELDI', 'codeldi')
        changes.save_all()
        self.assertFalse(usermain.has_option('HelpFiles', 'IDLE'))
        self.assertTrue(usermain.has_option('HelpFiles', 'ELDI'))

    def test_save_default(self):  # Cover 2nd and 3rd false branches.
        changes = self.changes
        changes.add_option('main', 'Indent', 'use-spaces', '1')
        # save_option returns False; cfg_type_changed remains False.

    # TODO: test that save_all calls usercfg Saves.

    def test_delete_section(self):
        changes = self.load()
        changes.delete_section('main', 'fake')  # Test no exception.
        self.assertEqual(changes, self.loaded)  # Test nothing deleted.
        for cfgtype, section in (('main', 'Msec'), ('keys', 'Ksec')):
            testcfg[cfgtype].SetOption(section, 'name', 'value')
            changes.delete_section(cfgtype, section)
            with self.assertRaises(KeyError):
                changes[cfgtype][section]  # Test section gone from changes
                testcfg[cfgtype][section]  # and from mock userCfg.
        # TODO test for save call.

    def test_clear(self):
        changes = self.load()
        changes.clear()
        self.assertEqual(changes, self.empty)


class WarningTest(unittest.TestCase):

    def test_warn(self):
        Equal = self.assertEqual
        config._warned = set()
        with captured_stderr() as stderr:
            config._warn('warning', 'key')
        Equal(config._warned, {('warning','key')})
        Equal(stderr.getvalue(), 'warning'+'\n')
        with captured_stderr() as stderr:
            config._warn('warning', 'key')
        Equal(stderr.getvalue(), '')
        with captured_stderr() as stderr:
            config._warn('warn2', 'yek')
        Equal(config._warned, {('warning','key'), ('warn2','yek')})
        Equal(stderr.getvalue(), 'warn2'+'\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
