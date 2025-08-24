# form.tcl --
#
# This demonstration script creates a simple form with a bunch
# of entry widgets.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .form
catch {destroy $w}
toplevel $w
wm title $w "Form Demonstration"
wm iconname $w "form"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "This window contains a simple form where you can type in the various entries and use tabs to move circularly between the entries."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

foreach i {f1 f2 f3 f4 f5} {
    frame $w.$i -bd 2
    entry $w.$i.entry -relief sunken -width 40
    label $w.$i.label
    pack $w.$i.entry -side right
    pack $w.$i.label -side left
}
$w.f1.label config -text Name:
$w.f2.label config -text Address:
$w.f5.label config -text Phone:
pack $w.msg $w.f1 $w.f2 $w.f3 $w.f4 $w.f5 -side top -fill x
bind $w <Return> "destroy $w"
focus $w.f1.entry
