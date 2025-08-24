# paned2.tcl --
#
# This demonstration script creates a toplevel window containing
# a paned window that separates two windows vertically.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .paned2
catch {destroy $w}
toplevel $w
wm title $w "Vertical Paned Window Demonstration"
wm iconname $w "paned2"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "The sash between the two scrolled windows below can be used to divide the area between them.  Use the left mouse button to resize without redrawing by just moving the sash, and use the middle mouse button to resize opaquely (always redrawing the windows in each position.)"
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

# Create the pane itself
panedwindow $w.pane -orient vertical
pack $w.pane -side top -expand yes -fill both -pady 2 -padx 2m

# The top window is a listbox with scrollbar
set paneList {
    {List of Tk Widgets}
    button
    canvas
    checkbutton
    entry
    frame
    label
    labelframe
    listbox
    menu
    menubutton
    message
    panedwindow
    radiobutton
    scale
    scrollbar
    spinbox
    text
    toplevel
}
set f [frame $w.pane.top]
listbox $f.list -listvariable paneList -yscrollcommand "$f.scr set"
# Invert the first item to highlight it
$f.list itemconfigure 0 \
	-background [$f.list cget -fg] -foreground [$f.list cget -bg]
ttk::scrollbar $f.scr -orient vertical -command "$f.list yview"
pack $f.scr -side right -fill y
pack $f.list -fill both -expand 1

# The bottom window is a text widget with scrollbar
set f [frame $w.pane.bottom]
text $f.text -xscrollcommand "$f.xscr set" -yscrollcommand "$f.yscr set" \
	-width 30 -height 8 -wrap none
ttk::scrollbar $f.xscr -orient horizontal -command "$f.text xview"
ttk::scrollbar $f.yscr -orient vertical -command "$f.text yview"
grid $f.text $f.yscr -sticky nsew
grid $f.xscr         -sticky nsew
grid columnconfigure $f 0 -weight 1
grid rowconfigure    $f 0 -weight 1
$f.text insert 1.0 "This is just a normal text widget"

# Now add our contents to the paned window
$w.pane add $w.pane.top $w.pane.bottom
