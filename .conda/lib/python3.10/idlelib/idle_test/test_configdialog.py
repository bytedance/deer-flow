"""Test configdialog, coverage 94%.

Half the class creates dialog, half works with user customizations.
"""
from idlelib import configdialog
from test.support import requires
requires('gui')
import unittest
from unittest import mock
from idlelib.idle_test.mock_idle import Func
from tkinter import (Tk, StringVar, IntVar, BooleanVar, DISABLED, NORMAL)
from idlelib import config
from idlelib.configdialog import idleConf, changes, tracers

# Tests should not depend on fortuitous user configurations.
# They must not affect actual user .cfg files.
# Use solution from test_config: empty parsers with no filename.
usercfg = idleConf.userCfg
testcfg = {
    'main': config.IdleUserConfParser(''),
    'highlight': config.IdleUserConfParser(''),
    'keys': config.IdleUserConfParser(''),
    'extensions': config.IdleUserConfParser(''),
}

root = None
dialog = None
mainpage = changes['main']
highpage = changes['highlight']
keyspage = changes['keys']
extpage = changes['extensions']


def setUpModule():
    global root, dialog
    idleConf.userCfg = testcfg
    root = Tk()
    # root.withdraw()    # Comment out, see issue 30870
    dialog = configdialog.ConfigDialog(root, 'Test', _utest=True)


def tearDownModule():
    global root, dialog
    idleConf.userCfg = usercfg
    tracers.detach()
    tracers.clear()
    changes.clear()
    root.update_idletasks()
    root.destroy()
    root = dialog = None


class ConfigDialogTest(unittest.TestCase):

    def test_deactivate_current_config(self):
        pass

    def activate_config_changes(self):
        pass


class ButtonTest(unittest.TestCase):

    def test_click_ok(self):
        d = dialog
        apply = d.apply = mock.Mock()
        destroy = d.destroy = mock.Mock()
        d.buttons['Ok'].invoke()
        apply.assert_called_once()
        destroy.assert_called_once()
        del d.destroy, d.apply

    def test_click_apply(self):
        d = dialog
        deactivate = d.deactivate_current_config = mock.Mock()
        save_ext = d.extpage.save_all_changed_extensions = mock.Mock()
        activate = d.activate_config_changes = mock.Mock()
        d.buttons['Apply'].invoke()
        deactivate.assert_called_once()
        save_ext.assert_called_once()
        activate.assert_called_once()
        del d.extpage.save_all_changed_extensions
        del d.activate_config_changes, d.deactivate_current_config

    def test_click_cancel(self):
        d = dialog
        d.destroy = Func()
        changes['main']['something'] = 1
        d.buttons['Cancel'].invoke()
        self.assertEqual(changes['main'], {})
        self.assertEqual(d.destroy.called, 1)
        del d.destroy

    def test_click_help(self):
        dialog.note.select(dialog.keyspage)
        with mock.patch.object(configdialog, 'view_text',
                               new_callable=Func) as view:
            dialog.buttons['Help'].invoke()
            title, contents = view.kwds['title'], view.kwds['contents']
        self.assertEqual(title, 'Help for IDLE preferences')
        self.assertTrue(contents.startswith('When you click') and
                        contents.endswith('a different name.\n'))


class FontPageTest(unittest.TestCase):
    """Test that font widgets enable users to make font changes.

    Test that widget actions set vars, that var changes add three
    options to changes and call set_samples, and that set_samples
    changes the font of both sample boxes.
    """
    @classmethod
    def setUpClass(cls):
        page = cls.page = dialog.fontpage
        dialog.note.select(page)
        page.set_samples = Func()  # Mask instance method.
        page.update()

    @classmethod
    def tearDownClass(cls):
        del cls.page.set_samples  # Unmask instance method.

    def setUp(self):
        changes.clear()

    def test_load_font_cfg(self):
        # Leave widget load test to human visual check.
        # TODO Improve checks when add IdleConf.get_font_values.
        tracers.detach()
        d = self.page
        d.font_name.set('Fake')
        d.font_size.set('1')
        d.font_bold.set(True)
        d.set_samples.called = 0
        d.load_font_cfg()
        self.assertNotEqual(d.font_name.get(), 'Fake')
        self.assertNotEqual(d.font_size.get(), '1')
        self.assertFalse(d.font_bold.get())
        self.assertEqual(d.set_samples.called, 1)
        tracers.attach()

    def test_fontlist_key(self):
        # Up and Down keys should select a new font.
        d = self.page
        if d.fontlist.size() < 2:
            self.skipTest('need at least 2 fonts')
        fontlist = d.fontlist
        fontlist.activate(0)
        font = d.fontlist.get('active')

        # Test Down key.
        fontlist.focus_force()
        fontlist.update()
        fontlist.event_generate('<Key-Down>')
        fontlist.event_generate('<KeyRelease-Down>')

        down_font = fontlist.get('active')
        self.assertNotEqual(down_font, font)
        self.assertIn(d.font_name.get(), down_font.lower())

        # Test Up key.
        fontlist.focus_force()
        fontlist.update()
        fontlist.event_generate('<Key-Up>')
        fontlist.event_generate('<KeyRelease-Up>')

        up_font = fontlist.get('active')
        self.assertEqual(up_font, font)
        self.assertIn(d.font_name.get(), up_font.lower())

    def test_fontlist_mouse(self):
        # Click on item should select that item.
        d = self.page
        if d.fontlist.size() < 2:
            self.skipTest('need at least 2 fonts')
        fontlist = d.fontlist
        fontlist.activate(0)

        # Select next item in listbox
        fontlist.focus_force()
        fontlist.see(1)
        fontlist.update()
        x, y, dx, dy = fontlist.bbox(1)
        x += dx // 2
        y += dy // 2
        fontlist.event_generate('<Button-1>', x=x, y=y)
        fontlist.event_generate('<ButtonRelease-1>', x=x, y=y)

        font1 = fontlist.get(1)
        select_font = fontlist.get('anchor')
        self.assertEqual(select_font, font1)
        self.assertIn(d.font_name.get(), font1.lower())

    def test_sizelist(self):
        # Click on number should select that number
        d = self.page
        d.sizelist.variable.set(40)
        self.assertEqual(d.font_size.get(), '40')

    def test_bold_toggle(self):
        # Click on checkbutton should invert it.
        d = self.page
        d.font_bold.set(False)
        d.bold_toggle.invoke()
        self.assertTrue(d.font_bold.get())
        d.bold_toggle.invoke()
        self.assertFalse(d.font_bold.get())

    def test_font_set(self):
        # Test that setting a font Variable results in 3 provisional
        # change entries and a call to set_samples. Use values sure to
        # not be defaults.

        default_font = idleConf.GetFont(root, 'main', 'EditorWindow')
        default_size = str(default_font[1])
        default_bold = default_font[2] == 'bold'
        d = self.page
        d.font_size.set(default_size)
        d.font_bold.set(default_bold)
        d.set_samples.called = 0

        d.font_name.set('Test Font')
        expected = {'EditorWindow': {'font': 'Test Font',
                                     'font-size': default_size,
                                     'font-bold': str(default_bold)}}
        self.assertEqual(mainpage, expected)
        self.assertEqual(d.set_samples.called, 1)
        changes.clear()

        d.font_size.set('20')
        expected = {'EditorWindow': {'font': 'Test Font',
                                     'font-size': '20',
                                     'font-bold': str(default_bold)}}
        self.assertEqual(mainpage, expected)
        self.assertEqual(d.set_samples.called, 2)
        changes.clear()

        d.font_bold.set(not default_bold)
        expected = {'EditorWindow': {'font': 'Test Font',
                                     'font-size': '20',
                                     'font-bold': str(not default_bold)}}
        self.assertEqual(mainpage, expected)
        self.assertEqual(d.set_samples.called, 3)

    def test_set_samples(self):
        d = self.page
        del d.set_samples  # Unmask method for test
        orig_samples = d.font_sample, d.highlight_sample
        d.font_sample, d.highlight_sample = {}, {}
        d.font_name.set('test')
        d.font_size.set('5')
        d.font_bold.set(1)
        expected = {'font': ('test', '5', 'bold')}

        # Test set_samples.
        d.set_samples()
        self.assertTrue(d.font_sample == d.highlight_sample == expected)

        d.font_sample, d.highlight_sample = orig_samples
        d.set_samples = Func()  # Re-mask for other tests.


class HighPageTest(unittest.TestCase):
    """Test that highlight tab widgets enable users to make changes.

    Test that widget actions set vars, that var changes add
    options to changes and that themes work correctly.
    """

    @classmethod
    def setUpClass(cls):
        page = cls.page = dialog.highpage
        dialog.note.select(page)
        page.set_theme_type = Func()
        page.paint_theme_sample = Func()
        page.set_highlight_target = Func()
        page.set_color_sample = Func()
        page.update()

    @classmethod
    def tearDownClass(cls):
        d = cls.page
        del d.set_theme_type, d.paint_theme_sample
        del d.set_highlight_target, d.set_color_sample

    def setUp(self):
        d = self.page
        # The following is needed for test_load_key_cfg, _delete_custom_keys.
        # This may indicate a defect in some test or function.
        for section in idleConf.GetSectionList('user', 'highlight'):
            idleConf.userCfg['highlight'].remove_section(section)
        changes.clear()
        d.set_theme_type.called = 0
        d.paint_theme_sample.called = 0
        d.set_highlight_target.called = 0
        d.set_color_sample.called = 0

    def test_load_theme_cfg(self):
        tracers.detach()
        d = self.page
        eq = self.assertEqual

        # Use builtin theme with no user themes created.
        idleConf.CurrentTheme = mock.Mock(return_value='IDLE Classic')
        d.load_theme_cfg()
        self.assertTrue(d.theme_source.get())
        # builtinlist sets variable builtin_name to the CurrentTheme default.
        eq(d.builtin_name.get(), 'IDLE Classic')
        eq(d.custom_name.get(), '- no custom themes -')
        eq(d.custom_theme_on.state(), ('disabled',))
        eq(d.set_theme_type.called, 1)
        eq(d.paint_theme_sample.called, 1)
        eq(d.set_highlight_target.called, 1)

        # Builtin theme with non-empty user theme list.
        idleConf.SetOption('highlight', 'test1', 'option', 'value')
        idleConf.SetOption('highlight', 'test2', 'option2', 'value2')
        d.load_theme_cfg()
        eq(d.builtin_name.get(), 'IDLE Classic')
        eq(d.custom_name.get(), 'test1')
        eq(d.set_theme_type.called, 2)
        eq(d.paint_theme_sample.called, 2)
        eq(d.set_highlight_target.called, 2)

        # Use custom theme.
        idleConf.CurrentTheme = mock.Mock(return_value='test2')
        idleConf.SetOption('main', 'Theme', 'default', '0')
        d.load_theme_cfg()
        self.assertFalse(d.theme_source.get())
        eq(d.builtin_name.get(), 'IDLE Classic')
        eq(d.custom_name.get(), 'test2')
        eq(d.set_theme_type.called, 3)
        eq(d.paint_theme_sample.called, 3)
        eq(d.set_highlight_target.called, 3)

        del idleConf.CurrentTheme
        tracers.attach()

    def test_theme_source(self):
        eq = self.assertEqual
        d = self.page
        # Test these separately.
        d.var_changed_builtin_name = Func()
        d.var_changed_custom_name = Func()
        # Builtin selected.
        d.builtin_theme_on.invoke()
        eq(mainpage, {'Theme': {'default': 'True'}})
        eq(d.var_changed_builtin_name.called, 1)
        eq(d.var_changed_custom_name.called, 0)
        changes.clear()

        # Custom selected.
        d.custom_theme_on.state(('!disabled',))
        d.custom_theme_on.invoke()
        self.assertEqual(mainpage, {'Theme': {'default': 'False'}})
        eq(d.var_changed_builtin_name.called, 1)
        eq(d.var_changed_custom_name.called, 1)
        del d.var_changed_builtin_name, d.var_changed_custom_name

    def test_builtin_name(self):
        eq = self.assertEqual
        d = self.page
        item_list = ['IDLE Classic', 'IDLE Dark', 'IDLE New']

        # Not in old_themes, defaults name to first item.
        idleConf.SetOption('main', 'Theme', 'name', 'spam')
        d.builtinlist.SetMenu(item_list, 'IDLE Dark')
        eq(mainpage, {'Theme': {'name': 'IDLE Classic',
                                'name2': 'IDLE Dark'}})
        eq(d.theme_message['text'], 'New theme, see Help')
        eq(d.paint_theme_sample.called, 1)

        # Not in old themes - uses name2.
        changes.clear()
        idleConf.SetOption('main', 'Theme', 'name', 'IDLE New')
        d.builtinlist.SetMenu(item_list, 'IDLE Dark')
        eq(mainpage, {'Theme': {'name2': 'IDLE Dark'}})
        eq(d.theme_message['text'], 'New theme, see Help')
        eq(d.paint_theme_sample.called, 2)

        # Builtin name in old_themes.
        changes.clear()
        d.builtinlist.SetMenu(item_list, 'IDLE Classic')
        eq(mainpage, {'Theme': {'name': 'IDLE Classic', 'name2': ''}})
        eq(d.theme_message['text'], '')
        eq(d.paint_theme_sample.called, 3)

    def test_custom_name(self):
        d = self.page

        # If no selections, doesn't get added.
        d.customlist.SetMenu([], '- no custom themes -')
        self.assertNotIn('Theme', mainpage)
        self.assertEqual(d.paint_theme_sample.called, 0)

        # Custom name selected.
        changes.clear()
        d.customlist.SetMenu(['a', 'b', 'c'], 'c')
        self.assertEqual(mainpage, {'Theme': {'name': 'c'}})
        self.assertEqual(d.paint_theme_sample.called, 1)

    def test_color(self):
        d = self.page
        d.on_new_color_set = Func()
        # self.color is only set in get_color through colorchooser.
        d.color.set('green')
        self.assertEqual(d.on_new_color_set.called, 1)
        del d.on_new_color_set

    def test_highlight_target_list_mouse(self):
        # Set highlight_target through targetlist.
        eq = self.assertEqual
        d = self.page

        d.targetlist.SetMenu(['a', 'b', 'c'], 'c')
        eq(d.highlight_target.get(), 'c')
        eq(d.set_highlight_target.called, 1)

    def test_highlight_target_text_mouse(self):
        # Set highlight_target through clicking highlight_sample.
        eq = self.assertEqual
        d = self.page

        elem = {}
        count = 0
        hs = d.highlight_sample
        hs.focus_force()
        hs.see(1.0)
        hs.update_idletasks()

        def tag_to_element(elem):
            for element, tag in d.theme_elements.items():
                elem[tag[0]] = element

        def click_it(start):
            x, y, dx, dy = hs.bbox(start)
            x += dx // 2
            y += dy // 2
            hs.event_generate('<Enter>', x=0, y=0)
            hs.event_generate('<Motion>', x=x, y=y)
            hs.event_generate('<ButtonPress-1>', x=x, y=y)
            hs.event_generate('<ButtonRelease-1>', x=x, y=y)

        # Flip theme_elements to make the tag the key.
        tag_to_element(elem)

        # If highlight_sample has a tag that isn't in theme_elements, there
        # will be a KeyError in the test run.
        for tag in hs.tag_names():
            for start_index in hs.tag_ranges(tag)[0::2]:
                count += 1
                click_it(start_index)
                eq(d.highlight_target.get(), elem[tag])
                eq(d.set_highlight_target.called, count)

    def test_highlight_sample_double_click(self):
        # Test double click on highlight_sample.
        eq = self.assertEqual
        d = self.page

        hs = d.highlight_sample
        hs.focus_force()
        hs.see(1.0)
        hs.update_idletasks()

        # Test binding from configdialog.
        hs.event_generate('<Enter>', x=0, y=0)
        hs.event_generate('<Motion>', x=0, y=0)
        # Double click is a sequence of two clicks in a row.
        for _ in range(2):
            hs.event_generate('<ButtonPress-1>', x=0, y=0)
            hs.event_generate('<ButtonRelease-1>', x=0, y=0)

        eq(hs.tag_ranges('sel'), ())

    def test_highlight_sample_b1_motion(self):
        # Test button motion on highlight_sample.
        eq = self.assertEqual
        d = self.page

        hs = d.highlight_sample
        hs.focus_force()
        hs.see(1.0)
        hs.update_idletasks()

        x, y, dx, dy, offset = hs.dlineinfo('1.0')

        # Test binding from configdialog.
        hs.event_generate('<Leave>')
        hs.event_generate('<Enter>')
        hs.event_generate('<Motion>', x=x, y=y)
        hs.event_generate('<ButtonPress-1>', x=x, y=y)
        hs.event_generate('<B1-Motion>', x=dx, y=dy)
        hs.event_generate('<ButtonRelease-1>', x=dx, y=dy)

        eq(hs.tag_ranges('sel'), ())

    def test_set_theme_type(self):
        eq = self.assertEqual
        d = self.page
        del d.set_theme_type

        # Builtin theme selected.
        d.theme_source.set(True)
        d.set_theme_type()
        eq(d.builtinlist['state'], NORMAL)
        eq(d.customlist['state'], DISABLED)
        eq(d.button_delete_custom.state(), ('disabled',))

        # Custom theme selected.
        d.theme_source.set(False)
        d.set_theme_type()
        eq(d.builtinlist['state'], DISABLED)
        eq(d.custom_theme_on.state(), ('selected',))
        eq(d.customlist['state'], NORMAL)
        eq(d.button_delete_custom.state(), ())
        d.set_theme_type = Func()

    def test_get_color(self):
        eq = self.assertEqual
        d = self.page
        orig_chooser = configdialog.colorchooser.askcolor
        chooser = configdialog.colorchooser.askcolor = Func()
        gntn = d.get_new_theme_name = Func()

        d.highlight_target.set('Editor Breakpoint')
        d.color.set('#ffffff')

        # Nothing selected.
        chooser.result = (None, None)
        d.button_set_color.invoke()
        eq(d.color.get(), '#ffffff')

        # Selection same as previous color.
        chooser.result = ('', d.style.lookup(d.frame_color_set['style'], 'background'))
        d.button_set_color.invoke()
        eq(d.color.get(), '#ffffff')

        # Select different color.
        chooser.result = ((222.8671875, 0.0, 0.0), '#de0000')

        # Default theme.
        d.color.set('#ffffff')
        d.theme_source.set(True)

        # No theme name selected therefore color not saved.
        gntn.result = ''
        d.button_set_color.invoke()
        eq(gntn.called, 1)
        eq(d.color.get(), '#ffffff')
        # Theme name selected.
        gntn.result = 'My New Theme'
        d.button_set_color.invoke()
        eq(d.custom_name.get(), gntn.result)
        eq(d.color.get(), '#de0000')

        # Custom theme.
        d.color.set('#ffffff')
        d.theme_source.set(False)
        d.button_set_color.invoke()
        eq(d.color.get(), '#de0000')

        del d.get_new_theme_name
        configdialog.colorchooser.askcolor = orig_chooser

    def test_on_new_color_set(self):
        d = self.page
        color = '#3f7cae'
        d.custom_name.set('Python')
        d.highlight_target.set('Selected Text')
        d.fg_bg_toggle.set(True)

        d.color.set(color)
        self.assertEqual(d.style.lookup(d.frame_color_set['style'], 'background'), color)
        self.assertEqual(d.highlight_sample.tag_cget('hilite', 'foreground'), color)
        self.assertEqual(highpage,
                         {'Python': {'hilite-foreground': color}})

    def test_get_new_theme_name(self):
        orig_sectionname = configdialog.SectionName
        sn = configdialog.SectionName = Func(return_self=True)
        d = self.page

        sn.result = 'New Theme'
        self.assertEqual(d.get_new_theme_name(''), 'New Theme')

        configdialog.SectionName = orig_sectionname

    def test_save_as_new_theme(self):
        d = self.page
        gntn = d.get_new_theme_name = Func()
        d.theme_source.set(True)

        # No name entered.
        gntn.result = ''
        d.button_save_custom.invoke()
        self.assertNotIn(gntn.result, idleConf.userCfg['highlight'])

        # Name entered.
        gntn.result = 'my new theme'
        gntn.called = 0
        self.assertNotIn(gntn.result, idleConf.userCfg['highlight'])
        d.button_save_custom.invoke()
        self.assertIn(gntn.result, idleConf.userCfg['highlight'])

        del d.get_new_theme_name

    def test_create_new_and_save_new(self):
        eq = self.assertEqual
        d = self.page

        # Use default as previously active theme.
        d.theme_source.set(True)
        d.builtin_name.set('IDLE Classic')
        first_new = 'my new custom theme'
        second_new = 'my second custom theme'

        # No changes, so themes are an exact copy.
        self.assertNotIn(first_new, idleConf.userCfg)
        d.create_new(first_new)
        eq(idleConf.GetSectionList('user', 'highlight'), [first_new])
        eq(idleConf.GetThemeDict('default', 'IDLE Classic'),
           idleConf.GetThemeDict('user', first_new))
        eq(d.custom_name.get(), first_new)
        self.assertFalse(d.theme_source.get())  # Use custom set.
        eq(d.set_theme_type.called, 1)

        # Test that changed targets are in new theme.
        changes.add_option('highlight', first_new, 'hit-background', 'yellow')
        self.assertNotIn(second_new, idleConf.userCfg)
        d.create_new(second_new)
        eq(idleConf.GetSectionList('user', 'highlight'), [first_new, second_new])
        self.assertNotEqual(idleConf.GetThemeDict('user', first_new),
                            idleConf.GetThemeDict('user', second_new))
        # Check that difference in themes was in `hit-background` from `changes`.
        idleConf.SetOption('highlight', first_new, 'hit-background', 'yellow')
        eq(idleConf.GetThemeDict('user', first_new),
           idleConf.GetThemeDict('user', second_new))

    def test_set_highlight_target(self):
        eq = self.assertEqual
        d = self.page
        del d.set_highlight_target

        # Target is cursor.
        d.highlight_target.set('Cursor')
        eq(d.fg_on.state(), ('disabled', 'selected'))
        eq(d.bg_on.state(), ('disabled',))
        self.assertTrue(d.fg_bg_toggle)
        eq(d.set_color_sample.called, 1)

        # Target is not cursor.
        d.highlight_target.set('Comment')
        eq(d.fg_on.state(), ('selected',))
        eq(d.bg_on.state(), ())
        self.assertTrue(d.fg_bg_toggle)
        eq(d.set_color_sample.called, 2)

        d.set_highlight_target = Func()

    def test_set_color_sample_binding(self):
        d = self.page
        scs = d.set_color_sample

        d.fg_on.invoke()
        self.assertEqual(scs.called, 1)

        d.bg_on.invoke()
        self.assertEqual(scs.called, 2)

    def test_set_color_sample(self):
        d = self.page
        del d.set_color_sample
        d.highlight_target.set('Selected Text')
        d.fg_bg_toggle.set(True)
        d.set_color_sample()
        self.assertEqual(
                d.style.lookup(d.frame_color_set['style'], 'background'),
                d.highlight_sample.tag_cget('hilite', 'foreground'))
        d.set_color_sample = Func()

    def test_paint_theme_sample(self):
        eq = self.assertEqual
        page = self.page
        del page.paint_theme_sample  # Delete masking mock.
        hs_tag = page.highlight_sample.tag_cget
        gh = idleConf.GetHighlight

        # Create custom theme based on IDLE Dark.
        page.theme_source.set(True)
        page.builtin_name.set('IDLE Dark')
        theme = 'IDLE Test'
        page.create_new(theme)
        page.set_color_sample.called = 0

        # Base theme with nothing in `changes`.
        page.paint_theme_sample()
        new_console = {'foreground': 'blue',
                       'background': 'yellow',}
        for key, value in new_console.items():
            self.assertNotEqual(hs_tag('console', key), value)
        eq(page.set_color_sample.called, 1)

        # Apply changes.
        for key, value in new_console.items():
            changes.add_option('highlight', theme, 'console-'+key, value)
        page.paint_theme_sample()
        for key, value in new_console.items():
            eq(hs_tag('console', key), value)
        eq(page.set_color_sample.called, 2)

        page.paint_theme_sample = Func()

    def test_delete_custom(self):
        eq = self.assertEqual
        d = self.page
        d.button_delete_custom.state(('!disabled',))
        yesno = d.askyesno = Func()
        dialog.deactivate_current_config = Func()
        dialog.activate_config_changes = Func()

        theme_name = 'spam theme'
        idleConf.userCfg['highlight'].SetOption(theme_name, 'name', 'value')
        highpage[theme_name] = {'option': 'True'}

        theme_name2 = 'other theme'
        idleConf.userCfg['highlight'].SetOption(theme_name2, 'name', 'value')
        highpage[theme_name2] = {'option': 'False'}

        # Force custom theme.
        d.custom_theme_on.state(('!disabled',))
        d.custom_theme_on.invoke()
        d.custom_name.set(theme_name)

        # Cancel deletion.
        yesno.result = False
        d.button_delete_custom.invoke()
        eq(yesno.called, 1)
        eq(highpage[theme_name], {'option': 'True'})
        eq(idleConf.GetSectionList('user', 'highlight'), [theme_name, theme_name2])
        eq(dialog.deactivate_current_config.called, 0)
        eq(dialog.activate_config_changes.called, 0)
        eq(d.set_theme_type.called, 0)

        # Confirm deletion.
        yesno.result = True
        d.button_delete_custom.invoke()
        eq(yesno.called, 2)
        self.assertNotIn(theme_name, highpage)
        eq(idleConf.GetSectionList('user', 'highlight'), [theme_name2])
        eq(d.custom_theme_on.state(), ())
        eq(d.custom_name.get(), theme_name2)
        eq(dialog.deactivate_current_config.called, 1)
        eq(dialog.activate_config_changes.called, 1)
        eq(d.set_theme_type.called, 1)

        # Confirm deletion of second theme - empties list.
        d.custom_name.set(theme_name2)
        yesno.result = True
        d.button_delete_custom.invoke()
        eq(yesno.called, 3)
        self.assertNotIn(theme_name, highpage)
        eq(idleConf.GetSectionList('user', 'highlight'), [])
        eq(d.custom_theme_on.state(), ('disabled',))
        eq(d.custom_name.get(), '- no custom themes -')
        eq(dialog.deactivate_current_config.called, 2)
        eq(dialog.activate_config_changes.called, 2)
        eq(d.set_theme_type.called, 2)

        del dialog.activate_config_changes, dialog.deactivate_current_config
        del d.askyesno


class KeysPageTest(unittest.TestCase):
    """Test that keys tab widgets enable users to make changes.

    Test that widget actions set vars, that var changes add
    options to changes and that key sets works correctly.
    """

    @classmethod
    def setUpClass(cls):
        page = cls.page = dialog.keyspage
        dialog.note.select(page)
        page.set_keys_type = Func()
        page.load_keys_list = Func()

    @classmethod
    def tearDownClass(cls):
        page = cls.page
        del page.set_keys_type, page.load_keys_list

    def setUp(self):
        d = self.page
        # The following is needed for test_load_key_cfg, _delete_custom_keys.
        # This may indicate a defect in some test or function.
        for section in idleConf.GetSectionList('user', 'keys'):
            idleConf.userCfg['keys'].remove_section(section)
        changes.clear()
        d.set_keys_type.called = 0
        d.load_keys_list.called = 0

    def test_load_key_cfg(self):
        tracers.detach()
        d = self.page
        eq = self.assertEqual

        # Use builtin keyset with no user keysets created.
        idleConf.CurrentKeys = mock.Mock(return_value='IDLE Classic OSX')
        d.load_key_cfg()
        self.assertTrue(d.keyset_source.get())
        # builtinlist sets variable builtin_name to the CurrentKeys default.
        eq(d.builtin_name.get(), 'IDLE Classic OSX')
        eq(d.custom_name.get(), '- no custom keys -')
        eq(d.custom_keyset_on.state(), ('disabled',))
        eq(d.set_keys_type.called, 1)
        eq(d.load_keys_list.called, 1)
        eq(d.load_keys_list.args, ('IDLE Classic OSX', ))

        # Builtin keyset with non-empty user keyset list.
        idleConf.SetOption('keys', 'test1', 'option', 'value')
        idleConf.SetOption('keys', 'test2', 'option2', 'value2')
        d.load_key_cfg()
        eq(d.builtin_name.get(), 'IDLE Classic OSX')
        eq(d.custom_name.get(), 'test1')
        eq(d.set_keys_type.called, 2)
        eq(d.load_keys_list.called, 2)
        eq(d.load_keys_list.args, ('IDLE Classic OSX', ))

        # Use custom keyset.
        idleConf.CurrentKeys = mock.Mock(return_value='test2')
        idleConf.default_keys = mock.Mock(return_value='IDLE Modern Unix')
        idleConf.SetOption('main', 'Keys', 'default', '0')
        d.load_key_cfg()
        self.assertFalse(d.keyset_source.get())
        eq(d.builtin_name.get(), 'IDLE Modern Unix')
        eq(d.custom_name.get(), 'test2')
        eq(d.set_keys_type.called, 3)
        eq(d.load_keys_list.called, 3)
        eq(d.load_keys_list.args, ('test2', ))

        del idleConf.CurrentKeys, idleConf.default_keys
        tracers.attach()

    def test_keyset_source(self):
        eq = self.assertEqual
        d = self.page
        # Test these separately.
        d.var_changed_builtin_name = Func()
        d.var_changed_custom_name = Func()
        # Builtin selected.
        d.builtin_keyset_on.invoke()
        eq(mainpage, {'Keys': {'default': 'True'}})
        eq(d.var_changed_builtin_name.called, 1)
        eq(d.var_changed_custom_name.called, 0)
        changes.clear()

        # Custom selected.
        d.custom_keyset_on.state(('!disabled',))
        d.custom_keyset_on.invoke()
        self.assertEqual(mainpage, {'Keys': {'default': 'False'}})
        eq(d.var_changed_builtin_name.called, 1)
        eq(d.var_changed_custom_name.called, 1)
        del d.var_changed_builtin_name, d.var_changed_custom_name

    def test_builtin_name(self):
        eq = self.assertEqual
        d = self.page
        idleConf.userCfg['main'].remove_section('Keys')
        item_list = ['IDLE Classic Windows', 'IDLE Classic OSX',
                     'IDLE Modern UNIX']

        # Not in old_keys, defaults name to first item.
        d.builtinlist.SetMenu(item_list, 'IDLE Modern UNIX')
        eq(mainpage, {'Keys': {'name': 'IDLE Classic Windows',
                               'name2': 'IDLE Modern UNIX'}})
        eq(d.keys_message['text'], 'New key set, see Help')
        eq(d.load_keys_list.called, 1)
        eq(d.load_keys_list.args, ('IDLE Modern UNIX', ))

        # Not in old keys - uses name2.
        changes.clear()
        idleConf.SetOption('main', 'Keys', 'name', 'IDLE Classic Unix')
        d.builtinlist.SetMenu(item_list, 'IDLE Modern UNIX')
        eq(mainpage, {'Keys': {'name2': 'IDLE Modern UNIX'}})
        eq(d.keys_message['text'], 'New key set, see Help')
        eq(d.load_keys_list.called, 2)
        eq(d.load_keys_list.args, ('IDLE Modern UNIX', ))

        # Builtin name in old_keys.
        changes.clear()
        d.builtinlist.SetMenu(item_list, 'IDLE Classic OSX')
        eq(mainpage, {'Keys': {'name': 'IDLE Classic OSX', 'name2': ''}})
        eq(d.keys_message['text'], '')
        eq(d.load_keys_list.called, 3)
        eq(d.load_keys_list.args, ('IDLE Classic OSX', ))

    def test_custom_name(self):
        d = self.page

        # If no selections, doesn't get added.
        d.customlist.SetMenu([], '- no custom keys -')
        self.assertNotIn('Keys', mainpage)
        self.assertEqual(d.load_keys_list.called, 0)

        # Custom name selected.
        changes.clear()
        d.customlist.SetMenu(['a', 'b', 'c'], 'c')
        self.assertEqual(mainpage, {'Keys': {'name': 'c'}})
        self.assertEqual(d.load_keys_list.called, 1)

    def test_keybinding(self):
        idleConf.SetOption('extensions', 'ZzDummy', 'enable', 'True')
        d = self.page
        d.custom_name.set('my custom keys')
        d.bindingslist.delete(0, 'end')
        d.bindingslist.insert(0, 'copy')
        d.bindingslist.insert(1, 'z-in')
        d.bindingslist.selection_set(0)
        d.bindingslist.selection_anchor(0)
        # Core binding - adds to keys.
        d.keybinding.set('<Key-F11>')
        self.assertEqual(keyspage,
                         {'my custom keys': {'copy': '<Key-F11>'}})

        # Not a core binding - adds to extensions.
        d.bindingslist.selection_set(1)
        d.bindingslist.selection_anchor(1)
        d.keybinding.set('<Key-F11>')
        self.assertEqual(extpage,
                         {'ZzDummy_cfgBindings': {'z-in': '<Key-F11>'}})

    def test_set_keys_type(self):
        eq = self.assertEqual
        d = self.page
        del d.set_keys_type

        # Builtin keyset selected.
        d.keyset_source.set(True)
        d.set_keys_type()
        eq(d.builtinlist['state'], NORMAL)
        eq(d.customlist['state'], DISABLED)
        eq(d.button_delete_custom_keys.state(), ('disabled',))

        # Custom keyset selected.
        d.keyset_source.set(False)
        d.set_keys_type()
        eq(d.builtinlist['state'], DISABLED)
        eq(d.custom_keyset_on.state(), ('selected',))
        eq(d.customlist['state'], NORMAL)
        eq(d.button_delete_custom_keys.state(), ())
        d.set_keys_type = Func()

    def test_get_new_keys(self):
        eq = self.assertEqual
        d = self.page
        orig_getkeysdialog = configdialog.GetKeysWindow
        gkd = configdialog.GetKeysWindow = Func(return_self=True)
        gnkn = d.get_new_keys_name = Func()

        d.button_new_keys.state(('!disabled',))
        d.bindingslist.delete(0, 'end')
        d.bindingslist.insert(0, 'copy - <Control-Shift-Key-C>')
        d.bindingslist.selection_set(0)
        d.bindingslist.selection_anchor(0)
        d.keybinding.set('Key-a')
        d.keyset_source.set(True)  # Default keyset.

        # Default keyset; no change to binding.
        gkd.result = ''
        d.button_new_keys.invoke()
        eq(d.bindingslist.get('anchor'), 'copy - <Control-Shift-Key-C>')
        # Keybinding isn't changed when there isn't a change entered.
        eq(d.keybinding.get(), 'Key-a')

        # Default keyset; binding changed.
        gkd.result = '<Key-F11>'
        # No keyset name selected therefore binding not saved.
        gnkn.result = ''
        d.button_new_keys.invoke()
        eq(gnkn.called, 1)
        eq(d.bindingslist.get('anchor'), 'copy - <Control-Shift-Key-C>')
        # Keyset name selected.
        gnkn.result = 'My New Key Set'
        d.button_new_keys.invoke()
        eq(d.custom_name.get(), gnkn.result)
        eq(d.bindingslist.get('anchor'), 'copy - <Key-F11>')
        eq(d.keybinding.get(), '<Key-F11>')

        # User keyset; binding changed.
        d.keyset_source.set(False)  # Custom keyset.
        gnkn.called = 0
        gkd.result = '<Key-p>'
        d.button_new_keys.invoke()
        eq(gnkn.called, 0)
        eq(d.bindingslist.get('anchor'), 'copy - <Key-p>')
        eq(d.keybinding.get(), '<Key-p>')

        del d.get_new_keys_name
        configdialog.GetKeysWindow = orig_getkeysdialog

    def test_get_new_keys_name(self):
        orig_sectionname = configdialog.SectionName
        sn = configdialog.SectionName = Func(return_self=True)
        d = self.page

        sn.result = 'New Keys'
        self.assertEqual(d.get_new_keys_name(''), 'New Keys')

        configdialog.SectionName = orig_sectionname

    def test_save_as_new_key_set(self):
        d = self.page
        gnkn = d.get_new_keys_name = Func()
        d.keyset_source.set(True)

        # No name entered.
        gnkn.result = ''
        d.button_save_custom_keys.invoke()

        # Name entered.
        gnkn.result = 'my new key set'
        gnkn.called = 0
        self.assertNotIn(gnkn.result, idleConf.userCfg['keys'])
        d.button_save_custom_keys.invoke()
        self.assertIn(gnkn.result, idleConf.userCfg['keys'])

        del d.get_new_keys_name

    def test_on_bindingslist_select(self):
        d = self.page
        b = d.bindingslist
        b.delete(0, 'end')
        b.insert(0, 'copy')
        b.insert(1, 'find')
        b.activate(0)

        b.focus_force()
        b.see(1)
        b.update()
        x, y, dx, dy = b.bbox(1)
        x += dx // 2
        y += dy // 2
        b.event_generate('<Enter>', x=0, y=0)
        b.event_generate('<Motion>', x=x, y=y)
        b.event_generate('<Button-1>', x=x, y=y)
        b.event_generate('<ButtonRelease-1>', x=x, y=y)
        self.assertEqual(b.get('anchor'), 'find')
        self.assertEqual(d.button_new_keys.state(), ())

    def test_create_new_key_set_and_save_new_key_set(self):
        eq = self.assertEqual
        d = self.page

        # Use default as previously active keyset.
        d.keyset_source.set(True)
        d.builtin_name.set('IDLE Classic Windows')
        first_new = 'my new custom key set'
        second_new = 'my second custom keyset'

        # No changes, so keysets are an exact copy.
        self.assertNotIn(first_new, idleConf.userCfg)
        d.create_new_key_set(first_new)
        eq(idleConf.GetSectionList('user', 'keys'), [first_new])
        eq(idleConf.GetKeySet('IDLE Classic Windows'),
           idleConf.GetKeySet(first_new))
        eq(d.custom_name.get(), first_new)
        self.assertFalse(d.keyset_source.get())  # Use custom set.
        eq(d.set_keys_type.called, 1)

        # Test that changed keybindings are in new keyset.
        changes.add_option('keys', first_new, 'copy', '<Key-F11>')
        self.assertNotIn(second_new, idleConf.userCfg)
        d.create_new_key_set(second_new)
        eq(idleConf.GetSectionList('user', 'keys'), [first_new, second_new])
        self.assertNotEqual(idleConf.GetKeySet(first_new),
                            idleConf.GetKeySet(second_new))
        # Check that difference in keysets was in option `copy` from `changes`.
        idleConf.SetOption('keys', first_new, 'copy', '<Key-F11>')
        eq(idleConf.GetKeySet(first_new), idleConf.GetKeySet(second_new))

    def test_load_keys_list(self):
        eq = self.assertEqual
        d = self.page
        gks = idleConf.GetKeySet = Func()
        del d.load_keys_list
        b = d.bindingslist

        b.delete(0, 'end')
        b.insert(0, '<<find>>')
        b.insert(1, '<<help>>')
        gks.result = {'<<copy>>': ['<Control-Key-c>', '<Control-Key-C>'],
                      '<<force-open-completions>>': ['<Control-Key-space>'],
                      '<<spam>>': ['<Key-F11>']}
        changes.add_option('keys', 'my keys', 'spam', '<Shift-Key-a>')
        expected = ('copy - <Control-Key-c> <Control-Key-C>',
                    'force-open-completions - <Control-Key-space>',
                    'spam - <Shift-Key-a>')

        # No current selection.
        d.load_keys_list('my keys')
        eq(b.get(0, 'end'), expected)
        eq(b.get('anchor'), '')
        eq(b.curselection(), ())

        # Check selection.
        b.selection_set(1)
        b.selection_anchor(1)
        d.load_keys_list('my keys')
        eq(b.get(0, 'end'), expected)
        eq(b.get('anchor'), 'force-open-completions - <Control-Key-space>')
        eq(b.curselection(), (1, ))

        # Change selection.
        b.selection_set(2)
        b.selection_anchor(2)
        d.load_keys_list('my keys')
        eq(b.get(0, 'end'), expected)
        eq(b.get('anchor'), 'spam - <Shift-Key-a>')
        eq(b.curselection(), (2, ))
        d.load_keys_list = Func()

        del idleConf.GetKeySet

    def test_delete_custom_keys(self):
        eq = self.assertEqual
        d = self.page
        d.button_delete_custom_keys.state(('!disabled',))
        yesno = d.askyesno = Func()
        dialog.deactivate_current_config = Func()
        dialog.activate_config_changes = Func()

        keyset_name = 'spam key set'
        idleConf.userCfg['keys'].SetOption(keyset_name, 'name', 'value')
        keyspage[keyset_name] = {'option': 'True'}

        keyset_name2 = 'other key set'
        idleConf.userCfg['keys'].SetOption(keyset_name2, 'name', 'value')
        keyspage[keyset_name2] = {'option': 'False'}

        # Force custom keyset.
        d.custom_keyset_on.state(('!disabled',))
        d.custom_keyset_on.invoke()
        d.custom_name.set(keyset_name)

        # Cancel deletion.
        yesno.result = False
        d.button_delete_custom_keys.invoke()
        eq(yesno.called, 1)
        eq(keyspage[keyset_name], {'option': 'True'})
        eq(idleConf.GetSectionList('user', 'keys'), [keyset_name, keyset_name2])
        eq(dialog.deactivate_current_config.called, 0)
        eq(dialog.activate_config_changes.called, 0)
        eq(d.set_keys_type.called, 0)

        # Confirm deletion.
        yesno.result = True
        d.button_delete_custom_keys.invoke()
        eq(yesno.called, 2)
        self.assertNotIn(keyset_name, keyspage)
        eq(idleConf.GetSectionList('user', 'keys'), [keyset_name2])
        eq(d.custom_keyset_on.state(), ())
        eq(d.custom_name.get(), keyset_name2)
        eq(dialog.deactivate_current_config.called, 1)
        eq(dialog.activate_config_changes.called, 1)
        eq(d.set_keys_type.called, 1)

        # Confirm deletion of second keyset - empties list.
        d.custom_name.set(keyset_name2)
        yesno.result = True
        d.button_delete_custom_keys.invoke()
        eq(yesno.called, 3)
        self.assertNotIn(keyset_name, keyspage)
        eq(idleConf.GetSectionList('user', 'keys'), [])
        eq(d.custom_keyset_on.state(), ('disabled',))
        eq(d.custom_name.get(), '- no custom keys -')
        eq(dialog.deactivate_current_config.called, 2)
        eq(dialog.activate_config_changes.called, 2)
        eq(d.set_keys_type.called, 2)

        del dialog.activate_config_changes, dialog.deactivate_current_config
        del d.askyesno


class WinPageTest(unittest.TestCase):
    """Test that general tab widgets enable users to make changes.

    Test that widget actions set vars, that var changes add
    options to changes.
    """
    @classmethod
    def setUpClass(cls):
        page = cls.page = dialog.winpage
        dialog.note.select(page)
        page.update()

    def setUp(self):
        changes.clear()

    def test_load_windows_cfg(self):
        # Set to wrong values, load, check right values.
        eq = self.assertEqual
        d = self.page
        d.startup_edit.set(1)
        d.win_width.set(1)
        d.win_height.set(1)
        d.load_windows_cfg()
        eq(d.startup_edit.get(), 0)
        eq(d.win_width.get(), '80')
        eq(d.win_height.get(), '40')

    def test_startup(self):
        d = self.page
        d.startup_editor_on.invoke()
        self.assertEqual(mainpage,
                         {'General': {'editor-on-startup': '1'}})
        changes.clear()
        d.startup_shell_on.invoke()
        self.assertEqual(mainpage,
                         {'General': {'editor-on-startup': '0'}})

    def test_editor_size(self):
        d = self.page
        d.win_height_int.delete(0, 'end')
        d.win_height_int.insert(0, '11')
        self.assertEqual(mainpage, {'EditorWindow': {'height': '11'}})
        changes.clear()
        d.win_width_int.delete(0, 'end')
        d.win_width_int.insert(0, '11')
        self.assertEqual(mainpage, {'EditorWindow': {'width': '11'}})

    def test_indent_spaces(self):
        d = self.page
        d.indent_chooser.set(6)
        self.assertEqual(d.indent_spaces.get(), '6')
        self.assertEqual(mainpage, {'Indent': {'num-spaces': '6'}})

    def test_cursor_blink(self):
        self.page.cursor_blink_bool.invoke()
        self.assertEqual(mainpage, {'EditorWindow': {'cursor-blink': 'False'}})

    def test_autocomplete_wait(self):
        self.page.auto_wait_int.delete(0, 'end')
        self.page.auto_wait_int.insert(0, '11')
        self.assertEqual(extpage, {'AutoComplete': {'popupwait': '11'}})

    def test_parenmatch(self):
        d = self.page
        eq = self.assertEqual
        d.paren_style_type['menu'].invoke(0)
        eq(extpage, {'ParenMatch': {'style': 'opener'}})
        changes.clear()
        d.paren_flash_time.delete(0, 'end')
        d.paren_flash_time.insert(0, '11')
        eq(extpage, {'ParenMatch': {'flash-delay': '11'}})
        changes.clear()
        d.bell_on.invoke()
        eq(extpage, {'ParenMatch': {'bell': 'False'}})

    def test_paragraph(self):
        self.page.format_width_int.delete(0, 'end')
        self.page.format_width_int.insert(0, '11')
        self.assertEqual(extpage, {'FormatParagraph': {'max-width': '11'}})


class ShedPageTest(unittest.TestCase):
    """Test that shed tab widgets enable users to make changes.

    Test that widget actions set vars, that var changes add
    options to changes.
    """
    @classmethod
    def setUpClass(cls):
        page = cls.page = dialog.shedpage
        dialog.note.select(page)
        page.update()

    def setUp(self):
        changes.clear()

    def test_load_shelled_cfg(self):
        # Set to wrong values, load, check right values.
        eq = self.assertEqual
        d = self.page
        d.autosave.set(1)
        d.load_shelled_cfg()
        eq(d.autosave.get(), 0)

    def test_autosave(self):
        d = self.page
        d.save_auto_on.invoke()
        self.assertEqual(mainpage, {'General': {'autosave': '1'}})
        d.save_ask_on.invoke()
        self.assertEqual(mainpage, {'General': {'autosave': '0'}})

    def test_context(self):
        self.page.context_int.delete(0, 'end')
        self.page.context_int.insert(0, '1')
        self.assertEqual(extpage, {'CodeContext': {'maxlines': '1'}})


#unittest.skip("Nothing here yet TODO")
class ExtPageTest(unittest.TestCase):
    """Test that the help source list works correctly."""
    @classmethod
    def setUpClass(cls):
        page = dialog.extpage
        dialog.note.select(page)


class HelpSourceTest(unittest.TestCase):
    """Test that the help source list works correctly."""
    @classmethod
    def setUpClass(cls):
        page = dialog.extpage
        dialog.note.select(page)
        frame = cls.frame = page.frame_help
        frame.set = frame.set_add_delete_state = Func()
        frame.upc = frame.update_help_changes = Func()
        frame.update()

    @classmethod
    def tearDownClass(cls):
        frame = cls.frame
        del frame.set, frame.set_add_delete_state
        del frame.upc, frame.update_help_changes
        frame.helplist.delete(0, 'end')
        frame.user_helplist.clear()

    def setUp(self):
        changes.clear()

    def test_load_helplist(self):
        eq = self.assertEqual
        fr = self.frame
        fr.helplist.insert('end', 'bad')
        fr.user_helplist = ['bad', 'worse']
        idleConf.SetOption('main', 'HelpFiles', '1', 'name;file')
        fr.load_helplist()
        eq(fr.helplist.get(0, 'end'), ('name',))
        eq(fr.user_helplist, [('name', 'file', '1')])

    def test_source_selected(self):
        fr = self.frame
        fr.set = fr.set_add_delete_state
        fr.upc = fr.update_help_changes
        helplist = fr.helplist
        dex = 'end'
        helplist.insert(dex, 'source')
        helplist.activate(dex)

        helplist.focus_force()
        helplist.see(dex)
        helplist.update()
        x, y, dx, dy = helplist.bbox(dex)
        x += dx // 2
        y += dy // 2
        fr.set.called = fr.upc.called = 0
        helplist.event_generate('<Enter>', x=0, y=0)
        helplist.event_generate('<Motion>', x=x, y=y)
        helplist.event_generate('<Button-1>', x=x, y=y)
        helplist.event_generate('<ButtonRelease-1>', x=x, y=y)
        self.assertEqual(helplist.get('anchor'), 'source')
        self.assertTrue(fr.set.called)
        self.assertFalse(fr.upc.called)

    def test_set_add_delete_state(self):
        # Call with 0 items, 1 unselected item, 1 selected item.
        eq = self.assertEqual
        fr = self.frame
        del fr.set_add_delete_state  # Unmask method.
        sad = fr.set_add_delete_state
        h = fr.helplist

        h.delete(0, 'end')
        sad()
        eq(fr.button_helplist_edit.state(), ('disabled',))
        eq(fr.button_helplist_remove.state(), ('disabled',))

        h.insert(0, 'source')
        sad()
        eq(fr.button_helplist_edit.state(), ('disabled',))
        eq(fr.button_helplist_remove.state(), ('disabled',))

        h.selection_set(0)
        sad()
        eq(fr.button_helplist_edit.state(), ())
        eq(fr.button_helplist_remove.state(), ())
        fr.set_add_delete_state = Func()  # Mask method.

    def test_helplist_item_add(self):
        # Call without and twice with HelpSource result.
        # Double call enables check on order.
        eq = self.assertEqual
        orig_helpsource = configdialog.HelpSource
        hs = configdialog.HelpSource = Func(return_self=True)
        fr = self.frame
        fr.helplist.delete(0, 'end')
        fr.user_helplist.clear()
        fr.set.called = fr.upc.called = 0

        hs.result = ''
        fr.helplist_item_add()
        self.assertTrue(list(fr.helplist.get(0, 'end')) ==
                        fr.user_helplist == [])
        self.assertFalse(fr.upc.called)

        hs.result = ('name1', 'file1')
        fr.helplist_item_add()
        hs.result = ('name2', 'file2')
        fr.helplist_item_add()
        eq(fr.helplist.get(0, 'end'), ('name1', 'name2'))
        eq(fr.user_helplist, [('name1', 'file1'), ('name2', 'file2')])
        eq(fr.upc.called, 2)
        self.assertFalse(fr.set.called)

        configdialog.HelpSource = orig_helpsource

    def test_helplist_item_edit(self):
        # Call without and with HelpSource change.
        eq = self.assertEqual
        orig_helpsource = configdialog.HelpSource
        hs = configdialog.HelpSource = Func(return_self=True)
        fr = self.frame
        fr.helplist.delete(0, 'end')
        fr.helplist.insert(0, 'name1')
        fr.helplist.selection_set(0)
        fr.helplist.selection_anchor(0)
        fr.user_helplist.clear()
        fr.user_helplist.append(('name1', 'file1'))
        fr.set.called = fr.upc.called = 0

        hs.result = ''
        fr.helplist_item_edit()
        hs.result = ('name1', 'file1')
        fr.helplist_item_edit()
        eq(fr.helplist.get(0, 'end'), ('name1',))
        eq(fr.user_helplist, [('name1', 'file1')])
        self.assertFalse(fr.upc.called)

        hs.result = ('name2', 'file2')
        fr.helplist_item_edit()
        eq(fr.helplist.get(0, 'end'), ('name2',))
        eq(fr.user_helplist, [('name2', 'file2')])
        self.assertTrue(fr.upc.called == fr.set.called == 1)

        configdialog.HelpSource = orig_helpsource

    def test_helplist_item_remove(self):
        eq = self.assertEqual
        fr = self.frame
        fr.helplist.delete(0, 'end')
        fr.helplist.insert(0, 'name1')
        fr.helplist.selection_set(0)
        fr.helplist.selection_anchor(0)
        fr.user_helplist.clear()
        fr.user_helplist.append(('name1', 'file1'))
        fr.set.called = fr.upc.called = 0

        fr.helplist_item_remove()
        eq(fr.helplist.get(0, 'end'), ())
        eq(fr.user_helplist, [])
        self.assertTrue(fr.upc.called == fr.set.called == 1)

    def test_update_help_changes(self):
        fr = self.frame
        del fr.update_help_changes
        fr.user_helplist.clear()
        fr.user_helplist.append(('name1', 'file1'))
        fr.user_helplist.append(('name2', 'file2'))

        fr.update_help_changes()
        self.assertEqual(mainpage['HelpFiles'],
                         {'1': 'name1;file1', '2': 'name2;file2'})
        fr.update_help_changes = Func()


class VarTraceTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tracers = configdialog.VarTrace()
        cls.iv = IntVar(root)
        cls.bv = BooleanVar(root)

    @classmethod
    def tearDownClass(cls):
        del cls.tracers, cls.iv, cls.bv

    def setUp(self):
        self.tracers.clear()
        self.called = 0

    def var_changed_increment(self, *params):
        self.called += 13

    def var_changed_boolean(self, *params):
        pass

    def test_init(self):
        tr = self.tracers
        tr.__init__()
        self.assertEqual(tr.untraced, [])
        self.assertEqual(tr.traced, [])

    def test_clear(self):
        tr = self.tracers
        tr.untraced.append(0)
        tr.traced.append(1)
        tr.clear()
        self.assertEqual(tr.untraced, [])
        self.assertEqual(tr.traced, [])

    def test_add(self):
        tr = self.tracers
        func = Func()
        cb = tr.make_callback = mock.Mock(return_value=func)

        iv = tr.add(self.iv, self.var_changed_increment)
        self.assertIs(iv, self.iv)
        bv = tr.add(self.bv, self.var_changed_boolean)
        self.assertIs(bv, self.bv)

        sv = StringVar(root)
        sv2 = tr.add(sv, ('main', 'section', 'option'))
        self.assertIs(sv2, sv)
        cb.assert_called_once()
        cb.assert_called_with(sv, ('main', 'section', 'option'))

        expected = [(iv, self.var_changed_increment),
                    (bv, self.var_changed_boolean),
                    (sv, func)]
        self.assertEqual(tr.traced, [])
        self.assertEqual(tr.untraced, expected)

        del tr.make_callback

    def test_make_callback(self):
        cb = self.tracers.make_callback(self.iv, ('main', 'section', 'option'))
        self.assertTrue(callable(cb))
        self.iv.set(42)
        # Not attached, so set didn't invoke the callback.
        self.assertNotIn('section', changes['main'])
        # Invoke callback manually.
        cb()
        self.assertIn('section', changes['main'])
        self.assertEqual(changes['main']['section']['option'], '42')
        changes.clear()

    def test_attach_detach(self):
        tr = self.tracers
        iv = tr.add(self.iv, self.var_changed_increment)
        bv = tr.add(self.bv, self.var_changed_boolean)
        expected = [(iv, self.var_changed_increment),
                    (bv, self.var_changed_boolean)]

        # Attach callbacks and test call increment.
        tr.attach()
        self.assertEqual(tr.untraced, [])
        self.assertCountEqual(tr.traced, expected)
        iv.set(1)
        self.assertEqual(iv.get(), 1)
        self.assertEqual(self.called, 13)

        # Check that only one callback is attached to a variable.
        # If more than one callback were attached, then var_changed_increment
        # would be called twice and the counter would be 2.
        self.called = 0
        tr.attach()
        iv.set(1)
        self.assertEqual(self.called, 13)

        # Detach callbacks.
        self.called = 0
        tr.detach()
        self.assertEqual(tr.traced, [])
        self.assertCountEqual(tr.untraced, expected)
        iv.set(1)
        self.assertEqual(self.called, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
