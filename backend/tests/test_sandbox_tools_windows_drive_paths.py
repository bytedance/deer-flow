r"""Windows host paths must not bypass the local host-bash guard.

``LocalSandbox`` is the documented default provider and executes through
PowerShell, cmd.exe or Git Bash on Windows, all of which resolve ``C:/...``,
``C:\...``, the drive-relative ``C:...`` form, a backslash root
(``\Windows\win.ini``, ``\\server\share``), a Win32 namespace path
(``\\?\C:\...``, ``\\.\PhysicalDrive0``) and a cmd/PowerShell variable
expansion (``%WINDIR%\win.ini``, ``$env:SystemRoot\win.ini``) against the host
filesystem. A deployment with ``sandbox.allow_host_bash: true`` therefore has
to reject those spellings exactly like the POSIX host paths
``validate_local_bash_command_paths`` already rejects, while regex, glob and
format text (``grep '\d'``, ``rg -g '*.py' '\Aclass' .``) stays an ordinary
argument.

These cases drive the Python validator, not a real Windows shell, so the host
gate is patched through fixtures and the whole file runs on every host -
including the Ubuntu CI jobs, which otherwise never reach the Windows branches.

Option arity is per tool, not one shared set: ``-l``/``-o``/``-I``/``-T`` are flags
for grep and rg but values in sed, gawk and perl. Reading a flag as value-taking
moves the pattern one word right, so ``grep -l foo \Windows\win.ini`` checked every
word except the file (``_WINDOWS_VALUE_OPTIONS_BY_COMMAND``).

Known limits, kept deliberately rather than re-bloating the guard:

* The escape-word exemption treats a word built from C/regex escape atoms as
  text wherever it stands, so ``grep -E '\C'``, ``sed -E 's/(a)\1/b/'``,
  ``type \C`` and ``type \d\n`` stay allowed where the pre-reduction patch
  rejected them as rooted names. They are regex/format arguments, never a host
  read, and telling them apart from a rooted name would need the per-tool
  escape tables this guard was reduced away from. The same rule rejects an
  assignment of regex text (``X=\bfoo``) that the pre-reduction patch allowed.
* ``grep '\bfoo' /mnt/user-data/workspace/a.txt`` is allowed: the file is an
  allowed mount, which the pre-reduction patch rejected as a rooted name.
"""

import pytest

from deerflow.sandbox import tools as sandbox_tools
from deerflow.sandbox.tools import validate_local_bash_command_paths

_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
}


@pytest.fixture()
def windows_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the validator's Windows path regardless of the actual host."""
    monkeypatch.setattr(sandbox_tools, "_is_windows", lambda: True)


@pytest.fixture()
def posix_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the validator's POSIX path regardless of the actual host."""
    monkeypatch.setattr(sandbox_tools, "_is_windows", lambda: False)


_ANY_REJECTION = "Unsafe absolute paths|Unsafe working directory change|path traversal"


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "cat C:/Windows/win.ini",
        "cat 'C:\\Windows\\win.ini'",
        "type C://Windows/win.ini",
        "cat C:/",
        "cat C:\\",
        "dir C:",
    ],
)
def test_blocks_drive_letter_host_paths(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "cd C:/Windows",
        "cd C:",
        "pushd C:\\Windows",
        "cd C:/Windows && type win.ini",
    ],
)
def test_blocks_drive_letter_cwd_targets(command: str) -> None:
    with pytest.raises(PermissionError, match=_ANY_REJECTION):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "type C:Windows/win.ini",
        "type C:Windows\\win.ini",
        "type a:b",
    ],
)
def test_blocks_drive_relative_host_paths(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "cat \\\\server\\share\\secret.txt",
        "cat '\\\\server\\share\\secret.txt'",
        "cd \\\\server\\share",
    ],
)
def test_blocks_backslash_unc_paths(command: str) -> None:
    with pytest.raises(PermissionError, match=_ANY_REJECTION):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "cat \\Windows\\win.ini",
        "cat '\\Windows\\win.ini'",
        "cd '\\Windows' && cat win.ini",
        "dir \\Boot\\BCD",
    ],
)
def test_blocks_backslash_rooted_paths(command: str) -> None:
    with pytest.raises(PermissionError, match=_ANY_REJECTION):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "cat %WINDIR%\\win.ini",
        "cat %SYSTEMDRIVE%\\Windows\\win.ini",
        "cat $env:SystemRoot\\win.ini",
        "cat $HOME\\.ssh\\id_rsa",
        "type %WINDIR:~0,3%Windows\\win.ini",
    ],
)
def test_blocks_expanded_windows_env_paths(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # A '/' root behind an option or provider prefix is a host path even
        # though ``_ABSOLUTE_PATH_PATTERN`` deliberately skips it.
        "Get-Content -Path:/Windows/win.ini",
        "Get-Content FileSystem::/Windows/win.ini",
        "Get-Content Microsoft.PowerShell.Core\\FileSystem::/Windows/win.ini",
        "curl -o/Windows/win.ini http://example.com/",
        # A backslash root behind the same prefixes.
        "Get-Content -Path:\\Windows\\win.ini",
        "curl -o\\Users\\Public\\evil.exe http://example.com/",
        "sort -o\\recovery file.txt",
        "X=\\Bootmgr",
        # cmd.exe treats ``,`` and ``=`` as argument delimiters.
        "type ,\\Windows\\win.ini",
        "type =\\Windows\\win.ini",
        "type ,\\\\server\\share\\secret.txt",
    ],
)
def test_blocks_rooted_paths_behind_a_value_prefix(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # A Win32 extended-length path is the same host path in every argument
        # position, and the ``\\?``/``\\.`` prefix must not read as an escape.
        "type \\\\?\\C:\\Windows\\win.ini",
        "type \\\\?\\C:\\",
        "type \\\\?\\D:\\finance\\q4.xlsx",
        'type "\\\\?\\C:\\Windows\\win.ini"',
        "Get-Content \\\\?\\C:\\Windows\\win.ini",
        "Get-Content -Path '\\\\?\\C:\\Windows\\win.ini'",
        "type \\\\?\\UNC\\server\\share\\secret.txt",
        "type \\\\?\\GLOBALROOT\\Device\\HarddiskVolume1\\Windows\\win.ini",
        "type \\\\.\\C:\\Windows\\win.ini",
        "type \\\\.\\PhysicalDrive0",
        'type "\\\\.\\PhysicalDrive0"',
    ],
)
def test_blocks_win32_namespace_paths(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # A drive path inside an interpreted script string is a host read: the
        # argument is one shell word, but the interpreter resolves the path.
        """python -c "open('C:/Windows/win.ini')" """,
        """python -c "import os; print(os.listdir('C:/Windows'))" """,
        """python -c "print('C:/Windows')" """,
        """python -c "from pathlib import Path; print(Path('C:/Windows').iterdir())" """,
        """perl -e 'open(F,"C:/Windows/win.ini")' """,
        """perl -e "print open('C:/Windows/win.ini')" """,
        """node -e "require('fs').readFileSync('C:/Windows/win.ini')" """,
        """bash -c "cat C:/Windows/win.ini" """,
        """bash -lc "cat C:/Windows/win.ini" """,
        """sh -c "cat \\\\Windows\\\\win.ini" """,
        """powershell -Command "Get-Content C:\\Windows\\win.ini" """,
        """powershell -Command "Get-Content -Path 'C:\\Windows\\win.ini'" """,
    ],
)
def test_blocks_drive_paths_inside_interpreted_scripts(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # The word is rooted with a backslash and its first segment is a drive
        # spec, so the escape heuristic must not read the pair as regex text.
        "type \\C:\\Windows\\win.ini",
        "type =\\C:\\Windows\\win.ini",
        "type ,\\C:\\Windows\\win.ini",
        "cat \\c:\\windows\\win.ini",
        "type \\n:\\Windows\\win.ini",
        "type \\.:\\Windows\\win.ini",
    ],
)
def test_blocks_rooted_words_whose_first_segment_is_a_drive(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # A shell drops the backslash in front of a character that carries no
        # escape meaning, so these reach the drive-relative and drive-root
        # spellings above. The first case is the maintainer-verified decoy: a
        # URL carrying ``C:`` text must not lend its context to the real word.
        "type C\\:Windows\\win.ini",
        "cat C\\:\\Windows\\win.ini",
        "type C\\:/Windows/win.ini",
        "curl 'https://x/?p=C:Windowswin.ini'; type C\\:Windows\\win.ini",
    ],
)
def test_blocks_backslash_escaped_drive_colon(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "type ..\\..\\secret.txt",
        "Get-Content ..\\..\\secret.txt",
        "cd ..\\..\\ && type secret.txt",
    ],
)
def test_blocks_unquoted_backslash_traversal(command: str) -> None:
    with pytest.raises(PermissionError, match="path traversal"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "type C^:/Windows/win.ini",
        "type C^:\\Windows\\win.ini",
        "cd C^:/Windows && type win.ini",
        "type ^\\Windows\\win.ini",
    ],
)
def test_blocks_cmd_caret_drive_paths(command: str) -> None:
    with pytest.raises(PermissionError, match=_ANY_REJECTION):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # cmd.exe matches command names case-insensitively and knows ``chdir``;
        # PowerShell spells it Set-Location/Push-Location (alias ``sl``).
        "CD %WINDIR% && type win.ini",
        "chdir %WINDIR% && type win.ini",
        "PUSHD %USERPROFILE%",
        "Set-Location $env:WINDIR && type win.ini",
        # A value-taking parameter binds before the directory argument.
        "Set-Location -ErrorAction Stop $env:WINDIR; Get-Content win.ini",
        "Set-Location -ErrorAction Stop -Path $env:WINDIR; Get-Content win.ini",
        "Push-Location -StackName saved $env:WINDIR; Get-Content win.ini",
        "cd -ErrorAction SilentlyContinue $env:WINDIR; Get-Content win.ini",
    ],
)
def test_blocks_windows_cwd_spellings(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe working directory change"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # A colon word is never a *relative* path on Windows, but it is still
        # text in a printed or pattern argument.
        "echo a:b",
        "grep 'a:b' file.txt",
        "grep -e 'a:b' file.txt",
        "Get-ChildItem -Filter 'a:*'",
    ],
)
def test_allows_colon_words_in_text_positions(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "grep '\\d' file.txt",
        "grep '\\Afoo' .",
        "grep '\\Qfoo\\E' .",
        "printf '\\t%s\\n'",
        "printf '%s,%d\\n' 1 2",
        "tr '\\n' ' '",
        "cut -d'\\t' -f1 file.txt",
        "sed -n 's/x/y/p' file.txt",
        "rsync --exclude=\\*.tar.gz a b",
    ],
)
def test_allows_escape_and_format_text(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # ``grep -E`` selects extended-regex mode; it is ripgrep's ``--encoding``
        # only there, so the pattern stays the first positional argument and a
        # regex escape in it is text rather than a drive-root name.
        "grep -E '\\bword\\b' file.txt",
        "grep -E '\\d+' file.txt",
        "grep -E '(foo|bar)' file.txt",
        "git grep -E '\\bfoo\\b'",
        "grep -rE '\\bfoo\\b' .",
        "grep -iE '\\btodo\\b' .",
        "sed -E 's/x/\\t/' file.txt",
        "rg -E utf-8 '\\Aclass' .",
        "grep -l foo file.txt",
        "grep -T foo file.txt",
    ],
)
def test_allows_grep_extended_regex_patterns(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # ripgrep's -g/-t take a glob/type value, so its value is not the search
        # pattern and the regex after it is not a file argument.
        "rg --glob '*.py' '\\Aclass' .",
        "rg -g '*.py' '\\Aclass' .",
        "rg --type py '\\Aclass' .",
        "rg -t py '\\Aclass' .",
        "rg -g '*.py' -e '\\Aclass' .",
        "rg -m 5 '\\Aclass' .",
        "rg -j 2 '\\Aclass' /mnt/user-data/workspace",
        "rg -o foo file.txt",
        "rg -I foo file.txt",
        "rg -T py foo file.txt",
    ],
)
def test_allows_ripgrep_pattern_arguments(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # The second positional after a glob/type option is an input path again.
        "rg -g '*.py' '\\Aclass' C:/Windows",
        "rg -t py '\\Aclass' \\Windows\\win.ini",
        # A pattern option moves the pattern out of the file position.
        "grep -e x \\Windows\\win.ini",
        "grep -F '\\d' \\Windows\\win.ini",
        "sed -n p '\\Bootmgr'",
        # Value-taking options keep consuming their value per tool.
        "sed -l 200 -n p \\Windows\\win.ini",
        "rg -T py foo \\Windows\\win.ini",
        "rg -E utf-8 foo \\Windows\\win.ini",
        "perl -I \\Windows\\inc -e 'print 1'",
        "Select-String -Path \\Windows\\win.ini -Pattern x",
    ],
)
def test_still_blocks_host_paths_in_pattern_tool_arguments(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # An option that supplies the pattern closes the pattern slot, attached
        # (``-efoo``, ``--regexp=foo``) or as the next word (``-f x``), so the
        # file after it is a file again; the script file itself is a path.
        "grep -efoo \\Windows\\win.ini",
        "sed -e's/x/y/' \\Windows\\win.ini",
        "grep -f x \\Windows\\win.ini",
        "awk -fprog.awk \\Windows\\win.ini",
        "grep --regexp=foo \\Windows\\win.ini",
        "grep -efoo \\\\server\\share\\secret.txt",
        "grep -f\\Windows\\patterns.txt file",
        # awk reads ``-E``/``--exec`` as a program file and ``-i``/``--include``
        # as a source file, so those values are host paths; ``-E`` is grep's
        # flag and rg's ``--encoding``, never awk's script there.
        "gawk -E \\Windows\\prog.awk data.txt",
        "gawk -i \\Windows\\prog.awk '{print}' data.txt",
        "gawk -E prog.awk \\Windows\\win.ini",
    ],
)
def test_blocks_file_after_a_pattern_supplying_option(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # ``-l``/``-o``/``-I``/``-T`` take no value for grep and rg (``grep
        # --help``: ``-l, --files-with-matches``, ``-o, --only-matching``,
        # ``-I`` alone, ``-T, --initial-tab``), so the next word is the pattern
        # and the word after it is a file again; ``sed -l N`` takes a value.
        "grep -l foo \\Windows\\win.ini",
        "grep --files-with-matches foo \\Windows\\win.ini",
        "grep -o foo \\Windows\\win.ini",
        "grep -I foo \\Windows\\win.ini",
        "grep -T foo \\Windows\\win.ini",
        "grep -il foo \\Windows\\win.ini",
        "rg -l foo \\Windows\\win.ini",
        "rg -o foo \\Windows\\win.ini",
        "rg -I foo \\Windows\\win.ini",
        "git grep -l foo \\Windows\\win.ini",
        "find . -exec grep -l foo \\Windows\\win.ini {} +",
    ],
)
def test_blocks_host_files_behind_flag_only_options(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # A short cluster is walked letter by letter: the letter that takes a
        # value owns the rest of the token (``-ieX`` is ``-i`` plus ``-e X``).
        "grep -iefoo \\Windows\\win.ini",
        "grep -ifpatterns \\Windows\\win.ini",
        "sed -ne's/x/y/' \\Windows\\win.ini",
    ],
)
def test_blocks_file_after_a_short_option_cluster(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # The raw ``..\`` scan runs on file positions, so closing the pattern
        # slot restores it there too.
        "grep -ex ..\\..\\secret.txt",
        "grep -iefoo ..\\..\\secret.txt",
    ],
)
def test_blocks_traversal_after_a_pattern_option(command: str) -> None:
    with pytest.raises(PermissionError, match="path traversal"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # A wrapper runs the command after its own flags and values, so the
        # wrapped command's argument roles are the ones that decide.
        "env grep -efoo \\Windows\\win.ini",
        "nice -n 5 grep -efoo \\Windows\\win.ini",
        "xargs -n 1 grep -efoo \\Windows\\win.ini",
        "find . -exec env grep -efoo \\Windows\\win.ini {} +",
        "nohup cat \\Windows\\win.ini",
    ],
)
def test_blocks_host_path_through_command_wrappers(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # The same wrappers must not turn regex text into a path: the pattern is
        # still the first positional argument of the wrapped command.
        "env grep '\\Afoo' file",
        "nice -n 5 grep '\\Afoo' file",
        "xargs -n1 grep '\\Afoo' file",
        "find . -name x -exec grep '\\Afoo' {} ;",
        # ``-l`` is a flag, so this word is the wrapped command's PATTERN.
        "find . -exec grep -l \\Windows\\win.ini {} +",
    ],
)
def test_allows_pattern_text_through_command_wrappers(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # A ``/``-rooted attached pattern value is text (awk's field separator,
        # sed's script, a regex after ``-e``), an attached ``=`` value consumes
        # only its own token, a long glob filter is text for every tool, and
        # cmd.exe decodes the caret before the tool sees the pattern.
        "awk -F/ '{print $1}' /mnt/user-data/workspace/a.txt",
        "sed -e/foo/d /mnt/user-data/workspace/a.txt",
        "rg -e'\\Aclass' .",
        "grep --max-count=1 '\\Afoo' file",
        "tar --exclude='*.py' -czf out.tgz .",
        "grep 'C^:/foo' /mnt/user-data/workspace/a.txt",
        # awk's program-file and assignment values are not paths to read.
        "gawk -E prog.awk data.txt",
        "gawk -v re=\\bfoo '{print}' /mnt/user-data/workspace/a.txt",
    ],
)
def test_allows_attached_pattern_and_glob_values(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        # An escape atom followed by a name is a rooted file, not text; ``-r``
        # is ripgrep's ``--replace`` only there; cmd.exe strips ``,`` and ``=``
        # before an attached option.
        "X=\\$Recycle.Bin",
        "type \\$Recycle.Bin",
        "grep -r TODO \\Windows\\win.ini",
        "curl ,-o\\Users\\Public\\evil.exe",
    ],
)
def test_blocks_host_paths_after_pattern_and_delimiter_shapes(command: str) -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "cat /mnt/user-data/workspace/a.txt",
        "cd /mnt/user-data/workspace",
        "chdir /mnt/user-data/workspace",
        "Set-Location -Path /mnt/user-data/workspace",
        "Set-Location -LiteralPath /mnt/user-data/workspace",
        "Set-Location -Path:/mnt/user-data/workspace",
        "Set-Location -PassThru /mnt/user-data/workspace",
        "Push-Location -StackName saved /mnt/user-data/workspace",
        "Get-Content -Path:/mnt/user-data/workspace/a.txt",
        "curl -o/mnt/user-data/outputs/x http://example.com/",
        "grep -r foo /mnt/user-data/workspace",
    ],
)
def test_allows_virtual_mounts_through_every_spelling(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("windows_host")
@pytest.mark.parametrize(
    "command",
    [
        "curl 'https://example.com/?next=C:/Windows/win.ini'",
        "curl https://example.com/packages/../archive.tar.gz -o /mnt/user-data/workspace/archive.tar.gz",
        "grep '^C:' file.txt",
        "echo a:b > out.txt",
    ],
)
def test_allows_url_and_anchor_text(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)


@pytest.mark.usefixtures("posix_host")
@pytest.mark.parametrize(
    "command",
    [
        "cat C:/Windows/win.ini",
        "cd C:/Windows",
        "type a:b",
        "cat '\\Windows\\win.ini'",
        "cat %WINDIR%\\win.ini",
        "type ..\\..\\secret.txt",
        "Get-Content -Path:/Windows/win.ini",
        "type \\\\?\\C:\\Windows\\win.ini",
        "type C\\:Windows\\win.ini",
        """python -c "open('C:/Windows/win.ini')" """,
    ],
)
def test_posix_keeps_windows_spellings_as_relative_names(command: str) -> None:
    validate_local_bash_command_paths(command, _THREAD_DATA)
