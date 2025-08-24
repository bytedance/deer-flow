# search.tcl --
#
# This demonstration script creates a collection of widgets that
# allow you to load a file into a text widget, then perform searches
# on that file.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

# textLoadFile --
# This procedure below loads a file into a text widget, discarding
# the previous contents of the widget. Tags for the old widget are
# not affected, however.
#
# Arguments:
# w -		The window into which to load the file.  Must be a
#		text widget.
# file -	The name of the file to load.  Must be readable.

proc textLoadFile {w file} {
    set f [open $file]
    $w delete 1.0 end
    while {![eof $f]} {
	$w insert end [read $f 10000]
    }
    close $f
}

# textSearch --
# Search for all instances of a given string in a text widget and
# apply a given tag to each instance found.
#
# Arguments:
# w -		The window in which to search.  Must be a text widget.
# string -	The string to search for.  The search is done using
#		exact matching only;  no special characters.
# tag -		Tag to apply to each instance of a matching string.

proc textSearch {w string tag} {
    $w tag remove search 0.0 end
    if {$string == ""} {
	return
    }
    set cur 1.0
    while 1 {
	set cur [$w search -count length $string $cur end]
	if {$cur == ""} {
	    break
	}
	$w tag add $tag $cur "$cur + $length char"
	set cur [$w index "$cur + $length char"]
    }
}

# textToggle --
# This procedure is invoked repeatedly to invoke two commands at
# periodic intervals.  It normally reschedules itself after each
# execution but if an error occurs (e.g. because the window was
# deleted) then it doesn't reschedule itself.
#
# Arguments:
# cmd1 -	Command to execute when procedure is called.
# sleep1 -	Ms to sleep after executing cmd1 before executing cmd2.
# cmd2 -	Command to execute in the *next* invocation of this
#		procedure.
# sleep2 -	Ms to sleep after executing cmd2 before executing cmd1 again.

proc textToggle {cmd1 sleep1 cmd2 sleep2} {
    catch {
	eval $cmd1
	after $sleep1 [list textToggle $cmd2 $sleep2 $cmd1 $sleep1]
    }
}

set w .search
catch {destroy $w}
toplevel $w
wm title $w "Text Demonstration - Search and Highlight"
wm iconname $w "search"
positionWindow $w

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

frame $w.file
label $w.file.label -text "File name:" -width 13 -anchor w
entry $w.file.entry -width 40 -textvariable fileName
button $w.file.button -text "Load File" \
	-command "textLoadFile $w.text \$fileName"
pack $w.file.label $w.file.entry -side left
pack $w.file.button -side left -pady 5 -padx 10
bind $w.file.entry <Return> "
    textLoadFile $w.text \$fileName
    focus $w.string.entry
"
focus $w.file.entry

frame $w.string
label $w.string.label -text "Search string:" -width 13 -anchor w
entry $w.string.entry -width 40 -textvariable searchString
button $w.string.button -text "Highlight" \
	-command "textSearch $w.text \$searchString search"
pack $w.string.label $w.string.entry -side left
pack $w.string.button -side left -pady 5 -padx 10
bind $w.string.entry <Return> "textSearch $w.text \$searchString search"

text $w.text -yscrollcommand "$w.scroll set" -setgrid true
ttk::scrollbar $w.scroll -command "$w.text yview"
pack $w.file $w.string -side top -fill x
pack $w.scroll -side right -fill y
pack $w.text -expand yes -fill both

# Set up display styles for text highlighting.

if {[winfo depth $w] > 1} {
    textToggle "$w.text tag configure search -background \
	    #ce5555 -foreground white" 800 "$w.text tag configure \
	    search -background {} -foreground {}" 200
} else {
    textToggle "$w.text tag configure search -background \
	    black -foreground white" 800 "$w.text tag configure \
	    search -background {} -foreground {}" 200
}
$w.text insert 1.0 \
{This window demonstrates how to use the tagging facilities in text
widgets to implement a searching mechanism.  First, type a file name
in the top entry, then type <Return> or click on "Load File".  Then
type a string in the lower entry and type <Return> or click on
"Load File".  This will cause all of the instances of the string to
be tagged with the tag "search", and it will arrange for the tag's
display attributes to change to make all of the strings blink.}
$w.text mark set insert 0.0

set fileName ""
set searchString ""
