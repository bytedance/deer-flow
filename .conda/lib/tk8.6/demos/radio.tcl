# radio.tcl --
#
# This demonstration script creates a toplevel window containing
# several radiobutton widgets.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .radio
catch {destroy $w}
toplevel $w
wm title $w "Radiobutton Demonstration"
wm iconname $w "radio"
positionWindow $w
label $w.msg -font $font -wraplength 5i -justify left -text "Three groups of radiobuttons are displayed below.  If you click on a button then the button will become selected exclusively among all the buttons in its group.  A Tcl variable is associated with each group to indicate which of the group's buttons is selected.  When the 'Tristate' button is pressed, the radio buttons will display the tri-state mode. Selecting any radio button will return the buttons to their respective on/off state. Click the \"See Variables\" button to see the current values of the variables."
grid $w.msg -row 0 -column 0 -columnspan 3 -sticky nsew

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w [list size color align]]
grid $btns -row 3 -column 0 -columnspan 3 -sticky ew

labelframe $w.left -pady 2 -text "Point Size" -padx 2
labelframe $w.mid -pady 2 -text "Color" -padx 2
labelframe $w.right -pady 2 -text "Alignment" -padx 2
button $w.tristate -text Tristate -command "set size multi; set color multi" \
    -pady 2 -padx 2
if {[tk windowingsystem] eq "aqua"} {
    $w.tristate configure -padx 10
}
grid $w.left     -column 0 -row 1 -pady .5c -padx .5c -rowspan 2
grid $w.mid      -column 1 -row 1 -pady .5c -padx .5c -rowspan 2
grid $w.right    -column 2 -row 1 -pady .5c -padx .5c
grid $w.tristate -column 2 -row 2 -pady .5c -padx .5c

foreach i {10 12 14 18 24} {
    radiobutton $w.left.b$i -text "Point Size $i" -variable size \
	    -relief flat -value $i -tristatevalue "multi"
    pack $w.left.b$i  -side top -pady 2 -anchor w -fill x
}

foreach c {Red Green Blue Yellow Orange Purple} {
    set lower [string tolower $c]
    radiobutton $w.mid.$lower -text $c -variable color \
	    -relief flat -value $lower -anchor w \
	    -command "$w.mid configure -fg \$color" \
	-tristatevalue "multi"
    pack $w.mid.$lower -side top -pady 2 -fill x
}


label $w.right.l -text "Label" -bitmap questhead -compound left
$w.right.l configure -width [winfo reqwidth $w.right.l] -compound top
$w.right.l configure -height [winfo reqheight $w.right.l]
foreach a {Top Left Right Bottom} {
    set lower [string tolower $a]
    radiobutton $w.right.$lower -text $a -variable align \
	    -relief flat -value $lower -indicatoron 0 -width 7 \
	    -command "$w.right.l configure -compound \$align"
}

grid x $w.right.top
grid $w.right.left $w.right.l $w.right.right
grid x $w.right.bottom
